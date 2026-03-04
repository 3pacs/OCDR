"""API routes for data import (F-01, F-02)."""

from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Body
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.ingestion.excel_ingestor import import_excel
from backend.app.parsing.x12_835_parser import import_835_file, import_835_folder
from backend.app.revenue.filing_deadlines import update_appeal_deadlines

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
