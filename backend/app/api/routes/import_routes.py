"""API routes for data import (F-01, F-02)."""

import logging
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Body, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.ingestion.excel_ingestor import import_excel
from backend.app.ingestion.flexible_excel_ingestor import import_excel_flexible, inspect_excel_file
from backend.app.ingestion.eob_scanner import scan_eob_folder
from backend.app.parsing.x12_835_parser import import_835_file, import_835_folder
from backend.app.revenue.filing_deadlines import update_appeal_deadlines
from backend.app.core.config import settings

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/excel")
async def upload_excel(
    file: UploadFile = File(...),
    sheet_name: str = "Current",
    db: AsyncSession = Depends(get_db),
):
    """Import OCMRI Excel file (F-01)."""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "File must be .xlsx or .xls")

    content = await file.read()
    try:
        result = await import_excel(content, db, sheet_name=sheet_name)
        # Update appeal deadlines after import
        deadlines_updated = await update_appeal_deadlines(db)
        result["appeal_deadlines_updated"] = deadlines_updated
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/835")
async def upload_835(
    file: UploadFile | None = File(None),
    folder_path: str | None = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """Import 835 ERA file or scan a folder (F-02)."""
    if file:
        content = await file.read()
        text = content.decode("utf-8", errors="replace")
        result = await import_835_file(text, file.filename, db)
        return result
    elif folder_path:
        try:
            result = await import_835_folder(folder_path, db)
            return result
        except ValueError as e:
            raise HTTPException(400, str(e))
    else:
        raise HTTPException(400, "Provide either a file upload or folder_path")


@router.post("/excel-flexible")
async def upload_excel_flexible(
    file: UploadFile = File(...),
    sheet_name: str | None = Query(None, description="Sheet to import (auto-detects if omitted)"),
    db: AsyncSession = Depends(get_db),
):
    """
    Import ANY Excel file with smart column detection (F-01 enhanced).

    - Auto-detects header row and fuzzy-matches columns to schema
    - Handles messy/inconsistent column names
    - Stores unmapped columns in extra_data JSONB (no data lost)
    - Supports 200MB+ files
    - Deduplicates on patient+date+scan+modality
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "File must be .xlsx or .xls")

    content = await file.read()
    logger.info(f"Flexible import: {file.filename} ({len(content)} bytes)")

    try:
        result = await import_excel_flexible(content, file.filename, db, sheet_name=sheet_name)
        # Update appeal deadlines after import
        deadlines_updated = await update_appeal_deadlines(db)
        result["appeal_deadlines_updated"] = deadlines_updated
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"Flexible import failed: {e}")
        raise HTTPException(500, f"Import failed: {str(e)}")


@router.post("/excel-inspect")
async def inspect_excel(
    file: UploadFile = File(...),
):
    """
    Preview an Excel file before importing: detect sheets, headers, and proposed column mappings.
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(400, "File must be .xlsx or .xls")

    content = await file.read()
    try:
        result = inspect_excel_file(content)
        result["filename"] = file.filename
        result["file_size_bytes"] = len(content)
        return result
    except Exception as e:
        raise HTTPException(500, f"Inspection failed: {str(e)}")


@router.get("/history")
async def import_history(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """List past imports."""
    from sqlalchemy import select, func, desc
    from backend.app.models.import_file import ImportFile

    total_result = await db.execute(select(func.count(ImportFile.id)))
    total = total_result.scalar()

    result = await db.execute(
        select(ImportFile)
        .order_by(desc(ImportFile.created_at))
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    items = result.scalars().all()

    return {
        "total": total,
        "page": page,
        "items": [
            {
                "id": f.id,
                "filename": f.filename,
                "sheet_name": f.sheet_name,
                "import_type": f.import_type,
                "status": f.status,
                "rows_imported": f.rows_imported,
                "rows_skipped": f.rows_skipped,
                "rows_errored": f.rows_errored,
                "column_mapping": f.column_mapping,
                "unmapped_columns": f.unmapped_columns,
                "created_at": f.created_at.isoformat() if f.created_at else None,
                "completed_at": f.completed_at.isoformat() if f.completed_at else None,
            }
            for f in items
        ],
    }


@router.post("/scan-eobs")
async def scan_eobs(
    folder_path: str | None = Body(None, embed=True),
    db: AsyncSession = Depends(get_db),
):
    """
    Recursively scan EOB folder for new files and import them.

    - Scans /app/data/eobs (or custom folder_path) and all subfolders
    - Skips files already in the database
    - Handles .835, .edi, .txt (X12), .xlsx, .xls (Excel)
    - Returns summary of what was found and imported
    """
    scan_path = folder_path or settings.EOBS_DIR
    try:
        result = await scan_eob_folder(scan_path, db)
        # Update appeal deadlines after scan
        deadlines_updated = await update_appeal_deadlines(db)
        result["appeal_deadlines_updated"] = deadlines_updated
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        logger.exception(f"EOB scan failed: {e}")
        raise HTTPException(500, f"Scan failed: {str(e)}")


@router.get("/scan-eobs/preview")
async def scan_eobs_preview(
    folder_path: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Preview what an EOB scan would find without importing."""
    import os
    from pathlib import Path
    from backend.app.ingestion.eob_scanner import _scan_directory, _get_processed_filenames

    scan_path = folder_path or settings.EOBS_DIR
    if not os.path.isdir(scan_path):
        raise HTTPException(400, f"Folder not found: {scan_path}")

    all_files = _scan_directory(scan_path)
    processed = await _get_processed_filenames(db)

    new_files = []
    already_done = []
    for fp, rel in all_files:
        ext = Path(fp).suffix.lower()
        size = os.path.getsize(fp)
        entry = {"path": rel, "extension": ext, "size_bytes": size}
        if rel in processed:
            already_done.append(entry)
        else:
            new_files.append(entry)

    return {
        "folder": scan_path,
        "total_files": len(all_files),
        "new_files": new_files,
        "new_count": len(new_files),
        "already_processed": already_done,
        "already_processed_count": len(already_done),
    }


@router.get("/status")
async def import_status(db: AsyncSession = Depends(get_db)):
    """Get import status (F-01)."""
    from sqlalchemy import select, func
    from backend.app.models.billing import BillingRecord

    result = await db.execute(
        select(
            func.count(BillingRecord.id),
            func.max(BillingRecord.created_at),
        )
    )
    row = result.one()
    return {
        "total_records": row[0],
        "last_import": row[1].isoformat() if row[1] else None,
    }
