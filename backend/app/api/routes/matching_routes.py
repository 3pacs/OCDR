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
from backend.app.models.billing import BillingRecord
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


@router.post("/crosswalk/verify-file")
async def verify_file_against_records(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload an extensionless/text file and test whether its lines match
    billing record Jacket IDs (patient_id column M).

    Reads each non-empty line, checks if the value appears as a patient_id
    in billing_records, and reports match statistics + sample matches.
    This helps verify what data is in unknown .NET server export files.
    """
    from sqlalchemy import select, func, distinct

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1", errors="replace")

    # Parse lines from file
    raw_lines = content.split("\n")
    lines = []
    for i, line in enumerate(raw_lines):
        stripped = line.strip()
        if stripped:
            lines.append({"line_num": i + 1, "raw": stripped})

    if not lines:
        return {"status": "empty", "message": "File has no non-empty lines"}

    # Load all Jacket IDs (patient_id) from billing records
    result = await db.execute(
        select(
            BillingRecord.patient_id,
            BillingRecord.patient_name,
            BillingRecord.topaz_id,
            BillingRecord.service_date,
        ).where(BillingRecord.patient_id.is_not(None))
    )
    billing_rows = result.all()

    # Build lookup: patient_id -> list of (name, topaz_id, date)
    jacket_lookup = {}
    for pid, pname, tid, sdate in billing_rows:
        key = str(pid).strip()
        jacket_lookup.setdefault(key, []).append({
            "patient_name": pname,
            "topaz_id": tid,
            "service_date": str(sdate) if sdate else None,
        })

    # Also build topaz_id lookup
    topaz_lookup = {}
    for pid, pname, tid, sdate in billing_rows:
        if tid:
            topaz_lookup.setdefault(str(tid).strip(), []).append({
                "patient_id": pid,
                "patient_name": pname,
                "service_date": str(sdate) if sdate else None,
            })

    # Test each line against both lookups
    jacket_matches = []
    topaz_matches = []
    no_match = []
    field_analysis = []  # For multi-field lines

    for entry in lines:
        raw = entry["raw"]
        line_num = entry["line_num"]

        # Check if line has delimiters (multi-field)
        fields = None
        if "|" in raw:
            fields = [f.strip() for f in raw.split("|")]
        elif "\t" in raw:
            fields = [f.strip() for f in raw.split("\t")]
        elif raw.count(",") >= 2:
            fields = [f.strip() for f in raw.split(",")]

        if fields:
            # Multi-field line: check each field
            matched_fields = []
            for fi, fval in enumerate(fields):
                if fval in jacket_lookup:
                    recs = jacket_lookup[fval]
                    matched_fields.append({
                        "field_index": fi,
                        "value": fval,
                        "match_type": "jacket_id",
                        "record_count": len(recs),
                        "sample_patient": recs[0]["patient_name"],
                    })
                elif fval in topaz_lookup:
                    recs = topaz_lookup[fval]
                    matched_fields.append({
                        "field_index": fi,
                        "value": fval,
                        "match_type": "topaz_id",
                        "record_count": len(recs),
                        "sample_patient": recs[0]["patient_name"],
                    })
            if matched_fields:
                field_analysis.append({
                    "line_num": line_num,
                    "fields": fields[:10],
                    "matches": matched_fields,
                })
            continue

        # Single-value line: clean and check
        # Try as-is, then as integer string
        test_vals = [raw]
        try:
            test_vals.append(str(int(float(raw))))
        except (ValueError, TypeError):
            pass

        matched = False
        for tv in test_vals:
            if tv in jacket_lookup:
                recs = jacket_lookup[tv]
                jacket_matches.append({
                    "line_num": line_num,
                    "value": raw,
                    "matched_as": tv,
                    "record_count": len(recs),
                    "sample_patient": recs[0]["patient_name"],
                    "sample_topaz": recs[0]["topaz_id"],
                })
                matched = True
                break
            elif tv in topaz_lookup:
                recs = topaz_lookup[tv]
                topaz_matches.append({
                    "line_num": line_num,
                    "value": raw,
                    "matched_as": tv,
                    "record_count": len(recs),
                    "sample_patient": recs[0]["patient_name"],
                    "sample_patient_id": recs[0]["patient_id"],
                })
                matched = True
                break

        if not matched:
            no_match.append({"line_num": line_num, "value": raw[:100]})

    total_lines = len(lines)
    total_jacket = len(jacket_matches)
    total_topaz = len(topaz_matches)
    total_field = len(field_analysis)
    total_no_match = len(no_match)

    # Determine file type verdict
    if total_field > 0:
        verdict = "multi_field"
        verdict_detail = (
            f"File has delimited rows. {total_field} lines analyzed. "
            f"Fields matching Jacket IDs and/or Topaz IDs found."
        )
    elif total_jacket > total_lines * 0.3:
        verdict = "jacket_id_list"
        verdict_detail = (
            f"{total_jacket}/{total_lines} lines ({round(total_jacket/total_lines*100, 1)}%) "
            f"match Jacket IDs (patient_id column M). This file likely contains Jacket/Chart IDs."
        )
    elif total_topaz > total_lines * 0.3:
        verdict = "topaz_id_list"
        verdict_detail = (
            f"{total_topaz}/{total_lines} lines ({round(total_topaz/total_lines*100, 1)}%) "
            f"match Topaz IDs. This file likely contains Topaz billing system IDs."
        )
    else:
        verdict = "unknown"
        verdict_detail = (
            f"Only {total_jacket} Jacket ID matches and {total_topaz} Topaz ID matches "
            f"out of {total_lines} lines. File content doesn't clearly map to known IDs."
        )

    return {
        "filename": file.filename,
        "total_lines": total_lines,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "jacket_id_matches": total_jacket,
        "topaz_id_matches": total_topaz,
        "multi_field_lines": total_field,
        "no_match": total_no_match,
        "unique_jacket_ids_in_db": len(jacket_lookup),
        "unique_topaz_ids_in_db": len(topaz_lookup),
        "sample_jacket_matches": jacket_matches[:25],
        "sample_topaz_matches": topaz_matches[:25],
        "sample_field_analysis": field_analysis[:25],
        "sample_no_match": no_match[:25],
        "first_10_lines": [l["raw"][:200] for l in lines[:10]],
    }
