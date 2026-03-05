"""API routes for auto-matching, crosswalk, and match review."""

import logging
from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.matching.auto_matcher import (
    run_auto_match,
    get_match_summary,
    get_unmatched_claims,
    get_matched_claims,
)
from backend.app.matching.pattern_clusterer import (
    analyze_crosswalk,
    propagate_topaz_ids,
    apply_topaz_crosswalk,
    get_crosswalk_stats,
)
from backend.app.parsing.topaz_export_parser import parse_topaz_export

logger = logging.getLogger(__name__)

router = APIRouter()


# --- Auto-Matching ---

@router.post("/run")
async def trigger_auto_match(db: AsyncSession = Depends(get_db)):
    """Run the 6-pass auto-matching engine on all unmatched ERA claims."""
    try:
        result = await run_auto_match(db)
        return result
    except Exception as e:
        logger.exception(f"Auto-match failed: {e}")
        return {"error": str(e)}


@router.get("/summary")
async def match_summary(db: AsyncSession = Depends(get_db)):
    """Get current matching statistics."""
    return await get_match_summary(db)


@router.get("/unmatched")
async def list_unmatched(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List unmatched ERA claims for manual review."""
    return await get_unmatched_claims(db, page, per_page)


@router.get("/matched")
async def list_matched(
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List matched ERA claims with billing record details."""
    return await get_matched_claims(db, page, per_page)


# --- Crosswalk (Chart Number <-> Topaz ID) ---

@router.get("/crosswalk/stats")
async def crosswalk_stats(db: AsyncSession = Depends(get_db)):
    """Get crosswalk coverage stats."""
    return await get_crosswalk_stats(db)


@router.get("/crosswalk/analyze")
async def crosswalk_analyze(db: AsyncSession = Depends(get_db)):
    """Analyze chart_number <-> topaz_id patterns from confirmed matches."""
    return await analyze_crosswalk(db)


class PropagateRequest(BaseModel):
    offset: int | None = None


@router.post("/crosswalk/propagate")
async def crosswalk_propagate(
    body: PropagateRequest = PropagateRequest(),
    db: AsyncSession = Depends(get_db),
):
    """Apply discovered offset pattern to assign topaz_id to unlinked billing records."""
    return await propagate_topaz_ids(db, offset=body.offset)


# --- Topaz Export Crosswalk ---

@router.post("/crosswalk/import-topaz")
async def import_topaz_crosswalk(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a Topaz server export file to extract and apply the
    chart_number ↔ topaz_id crosswalk.

    Accepts any file format — auto-detects pipe/tab/CSV/XML/fixed-width.
    Extensionless .NET export files from the Topaz server are supported.
    """
    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1", errors="replace")

    filename = file.filename or "upload"

    # Parse the export
    parsed = parse_topaz_export(content, filename)

    if not parsed.crosswalk_pairs:
        return {
            "status": "no_crosswalk_data",
            "format": parsed.format_detected,
            "headers_found": parsed.headers_found[:20],
            "column_mapping": parsed.column_mapping,
            "warnings": parsed.warnings,
            "message": (
                "No chart_number or topaz_id columns detected. "
                f"Headers found: {parsed.headers_found[:20]}. "
                "Ensure the file contains columns like 'Chart Number', 'Patient ID', "
                "'Billing ID', 'Claim ID', 'Account', etc."
            ),
        }

    # Apply crosswalk to billing records
    apply_result = await apply_topaz_crosswalk(db, parsed.crosswalk_pairs)

    return {
        "status": "success",
        "file": filename,
        "format": parsed.format_detected,
        "headers_found": parsed.headers_found[:20],
        "column_mapping": parsed.column_mapping,
        "total_rows_parsed": parsed.total_rows,
        "crosswalk_applied": apply_result,
        "extra_fields": parsed.extra_fields[:20],
        "warnings": parsed.warnings,
    }


@router.post("/crosswalk/preview-topaz")
async def preview_topaz_crosswalk(
    file: UploadFile = File(...),
):
    """
    Preview a Topaz export file without applying changes.

    Returns detected format, headers, column mapping, and sample crosswalk pairs.
    """
    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1", errors="replace")

    parsed = parse_topaz_export(content, file.filename or "preview")

    return {
        "format": parsed.format_detected,
        "headers_found": parsed.headers_found[:30],
        "column_mapping": parsed.column_mapping,
        "total_rows": parsed.total_rows,
        "sample_pairs": parsed.crosswalk_pairs[:20],
        "extra_fields": parsed.extra_fields[:20],
        "warnings": parsed.warnings,
    }
