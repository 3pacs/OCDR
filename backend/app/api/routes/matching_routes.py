"""API routes for auto-matching, crosswalk, and match review."""

import logging
import json
from fastapi import APIRouter, Depends, File, Form, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
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


class TopazIdUpdate(BaseModel):
    billing_record_id: int
    topaz_id: str | None = None
    patient_id: str | None = None


class TopazIdBulkUpdate(BaseModel):
    updates: list[TopazIdUpdate] = Field(..., max_length=500)


@router.patch("/crosswalk/update-ids")
async def update_crosswalk_ids(
    body: TopazIdBulkUpdate,
    db: AsyncSession = Depends(get_db),
):
    """
    Update topaz_id and/or patient_id on individual billing records.

    Used for manual correction after reviewing crosswalk import results.
    Accepts up to 500 updates at once.
    """
    applied = 0
    not_found = 0

    for upd in body.updates:
        result = await db.execute(
            select(BillingRecord).where(BillingRecord.id == upd.billing_record_id)
        )
        record = result.scalar_one_or_none()
        if not record:
            not_found += 1
            continue

        changed = False
        if upd.topaz_id is not None:
            record.topaz_id = upd.topaz_id if upd.topaz_id else None
            changed = True
        if upd.patient_id is not None:
            record.patient_id = upd.patient_id if upd.patient_id else None
            changed = True
        if changed:
            applied += 1

    if applied > 0:
        await db.commit()

    return {
        "status": "success",
        "applied": applied,
        "not_found": not_found,
        "total_requested": len(body.updates),
    }


@router.get("/crosswalk/integrity")
async def crosswalk_integrity_check(
    db: AsyncSession = Depends(get_db),
):
    """
    Audit crosswalk data for inconsistencies.

    Checks:
    1. Same patient_id with different topaz_ids (conflicting mappings)
    2. Same topaz_id assigned to different patient_ids
    3. Matched ERA claims where patient name doesn't corroborate
    4. Records where topaz_id was learned from matching but name similarity is low
    """
    from sqlalchemy import select, func, distinct
    from rapidfuzz import fuzz
    from backend.app.models.era import ERAClaimLine

    # 1. Conflicting mappings: same patient_id → multiple topaz_ids
    result = await db.execute(
        select(
            BillingRecord.patient_id,
            BillingRecord.topaz_id,
            BillingRecord.patient_name,
        ).where(
            BillingRecord.patient_id.is_not(None),
            BillingRecord.topaz_id.is_not(None),
        ).order_by(BillingRecord.patient_id)
    )
    all_pairs = result.all()

    # Group by patient_id
    by_jacket = {}
    for pid, tid, pname in all_pairs:
        key = str(pid).strip()
        by_jacket.setdefault(key, []).append({
            "topaz_id": str(tid).strip(),
            "patient_name": pname,
        })

    # Find conflicting jacket→topaz mappings
    conflicting_jacket = []
    for jacket_id, entries in by_jacket.items():
        unique_topaz = set(e["topaz_id"] for e in entries)
        if len(unique_topaz) > 1:
            conflicting_jacket.append({
                "jacket_id": jacket_id,
                "topaz_ids": list(unique_topaz),
                "patient_names": list(set(e["patient_name"] for e in entries)),
                "record_count": len(entries),
            })

    # 2. Same topaz_id → multiple patient_ids
    by_topaz = {}
    for pid, tid, pname in all_pairs:
        key = str(tid).strip()
        by_topaz.setdefault(key, []).append({
            "patient_id": str(pid).strip(),
            "patient_name": pname,
        })

    conflicting_topaz = []
    for topaz_id, entries in by_topaz.items():
        unique_jackets = set(e["patient_id"] for e in entries)
        if len(unique_jackets) > 1:
            conflicting_topaz.append({
                "topaz_id": topaz_id,
                "jacket_ids": list(unique_jackets),
                "patient_names": list(set(e["patient_name"] for e in entries)),
                "record_count": len(entries),
            })

    # 3. Matched claims: verify name corroboration
    matched_result = await db.execute(
        select(
            ERAClaimLine.claim_id,
            ERAClaimLine.patient_name_835,
            ERAClaimLine.service_date_835,
            ERAClaimLine.match_confidence,
            BillingRecord.patient_name,
            BillingRecord.patient_id,
            BillingRecord.topaz_id,
            BillingRecord.service_date,
        )
        .join(BillingRecord, ERAClaimLine.matched_billing_id == BillingRecord.id)
        .where(ERAClaimLine.matched_billing_id.is_not(None))
    )
    matched_rows = matched_result.all()

    name_mismatches = []
    date_mismatches = []
    for (claim_id, era_name, era_date, confidence,
         billing_name, jacket_id, topaz_id, billing_date) in matched_rows:
        # Name check
        n1 = (era_name or "").upper().strip()
        n2 = (billing_name or "").upper().strip()
        if n1 and n2:
            name_score = fuzz.token_sort_ratio(n1, n2)
            if name_score < 70:
                name_mismatches.append({
                    "claim_id": claim_id,
                    "era_patient": era_name,
                    "billing_patient": billing_name,
                    "name_similarity": name_score,
                    "confidence": float(confidence) if confidence else None,
                    "jacket_id": str(jacket_id) if jacket_id else None,
                    "topaz_id": topaz_id,
                })
        # Date check
        if era_date and billing_date and era_date != billing_date:
            delta = abs((era_date - billing_date).days)
            if delta > 3:
                date_mismatches.append({
                    "claim_id": claim_id,
                    "era_date": str(era_date),
                    "billing_date": str(billing_date),
                    "days_apart": delta,
                    "era_patient": era_name,
                    "billing_patient": billing_name,
                    "confidence": float(confidence) if confidence else None,
                })

    total_matched = len(matched_rows)
    issues_found = (
        len(conflicting_jacket) +
        len(conflicting_topaz) +
        len(name_mismatches) +
        len(date_mismatches)
    )

    return {
        "status": "clean" if issues_found == 0 else "issues_found",
        "total_crosswalk_pairs": len(all_pairs),
        "total_matched_claims": total_matched,
        "issues_found": issues_found,
        "conflicting_jacket_to_topaz": conflicting_jacket[:50],
        "conflicting_topaz_to_jacket": conflicting_topaz[:50],
        "name_mismatches": name_mismatches[:50],
        "date_mismatches": date_mismatches[:50],
        "summary": {
            "jacket_conflicts": len(conflicting_jacket),
            "topaz_conflicts": len(conflicting_topaz),
            "name_mismatches": len(name_mismatches),
            "date_mismatches": len(date_mismatches),
        },
    }


# --- Topaz Export Crosswalk ---

@router.post("/crosswalk/import-topaz")
async def import_topaz_crosswalk(
    file: UploadFile = File(...),
    field_mapping: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a Topaz server export file to extract and apply the
    chart_number ↔ topaz_id crosswalk.

    Accepts any file format — auto-detects pipe/tab/CSV/XML/fixed-width.

    For fixed-width files, the line number IS the Topaz patient ID.

    Optional field_mapping (JSON string) lets the user override auto-detected
    field roles. Format: {"chart_number": "id_2", "patient_name": "name_1"}
    where the values are zone labels from the preview step.
    """
    from backend.app.parsing.fixed_width_parser import (
        looks_like_fixed_width,
        parse_fixed_width_records,
    )

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1", errors="replace")

    filename = file.filename or "upload"

    # Parse user-provided field mapping
    user_mapping = {}
    if field_mapping:
        try:
            user_mapping = json.loads(field_mapping)
        except (json.JSONDecodeError, TypeError):
            pass

    # ── Fixed-width .NET server file: line number = Topaz patient ID ──
    if looks_like_fixed_width(content_bytes):
        fw_result = parse_fixed_width_records(content_bytes)
        if fw_result.total_records > 0:
            # Determine which zone labels map to which roles.
            # User mapping overrides auto-detected fields.
            chart_fields = []
            name_fields = []

            if user_mapping.get("chart_number"):
                chart_fields = [user_mapping["chart_number"]]
            else:
                chart_fields = list(fw_result.id_fields)

            if user_mapping.get("patient_name"):
                name_fields = [user_mapping["patient_name"]]
            else:
                name_fields = list(fw_result.name_fields)

            crosswalk_pairs = []
            for rec in fw_result.records:
                topaz_id = rec.get("_topaz_id")
                if not topaz_id:
                    continue

                chart_number = None
                for field_label in chart_fields:
                    val = rec.get(field_label, "").strip()
                    if val:
                        try:
                            chart_number = str(int(float(val)))
                        except (ValueError, TypeError):
                            chart_number = val
                        break

                patient_name = None
                for field_label in name_fields:
                    val = rec.get(field_label, "").strip()
                    if val:
                        patient_name = val
                        break

                if chart_number or patient_name:
                    crosswalk_pairs.append({
                        "topaz_id": topaz_id,
                        "chart_number": chart_number,
                        "patient_name": patient_name,
                    })

            if not crosswalk_pairs:
                return {
                    "status": "no_crosswalk_data",
                    "format": "fixed_width",
                    "total_records": fw_result.total_records,
                    "field_zones": fw_result.field_zones,
                    "warnings": fw_result.warnings + [
                        "No records had usable data in the selected fields. "
                        "Try assigning different field zones."
                    ],
                    "message": (
                        f"Parsed {fw_result.total_records:,} fixed-width records "
                        f"but the selected fields produced no crosswalk pairs. "
                        f"Try a different field mapping."
                    ),
                }

            apply_result = await apply_topaz_crosswalk(db, crosswalk_pairs)

            return {
                "status": "success",
                "file": filename,
                "format": "fixed_width",
                "format_detail": (
                    f"Fixed-width: {fw_result.total_records:,} records x "
                    f"{fw_result.record_width} bytes. Line# = Topaz ID."
                ),
                "total_records": fw_result.total_records,
                "crosswalk_pairs_extracted": len(crosswalk_pairs),
                "field_mapping_used": {
                    "chart_number": chart_fields[0] if chart_fields else None,
                    "patient_name": name_fields[0] if name_fields else None,
                },
                "field_zones": fw_result.field_zones,
                "crosswalk_applied": apply_result,
                "sample_pairs": crosswalk_pairs[:20],
                "warnings": fw_result.warnings,
            }

    # ── Delimited / XML / other formats ──
    parsed = parse_topaz_export(content, filename)

    # If user provided header overrides, re-extract crosswalk pairs
    # using the user's column names instead of auto-detected ones.
    if user_mapping and parsed.raw_rows:
        crosswalk_pairs = []
        for raw_row in parsed.raw_rows:
            pair = {}
            for role, header_name in user_mapping.items():
                if role in ("chart_number", "topaz_id", "patient_name", "service_date"):
                    val = raw_row.get(header_name, "").strip()
                    if val:
                        pair[role] = val
            if pair.get("chart_number") or pair.get("topaz_id"):
                crosswalk_pairs.append(pair)
        if crosswalk_pairs:
            parsed.crosswalk_pairs = crosswalk_pairs
            parsed.total_rows = len(crosswalk_pairs)
            parsed.column_mapping = {
                role: header for role, header in user_mapping.items()
                if role in ("chart_number", "topaz_id", "patient_name", "service_date")
            }

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
                "Use the Preview step to see all headers and assign them manually."
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

    Returns detected format, all field zones with sample values, and
    auto-detected column mapping (which the user can override before import).
    """
    from backend.app.parsing.fixed_width_parser import (
        looks_like_fixed_width,
        parse_fixed_width_records,
    )

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1", errors="replace")

    # ── Fixed-width preview ──
    if looks_like_fixed_width(content_bytes):
        fw_result = parse_fixed_width_records(content_bytes)
        if fw_result.total_records > 0:
            # Return ALL zones with expanded sample values so the user
            # can see what each field contains and assign roles manually.
            zones_with_samples = []
            for z in fw_result.field_zones:
                # Gather more sample values from populated records
                samples = []
                for rec in fw_result.records[:50]:
                    val = rec.get(z["label"], "")
                    if val and val not in samples:
                        samples.append(val)
                    if len(samples) >= 8:
                        break
                zones_with_samples.append({
                    **z,
                    "sample_values": samples,
                })

            # Build sample records showing all field values
            sample_records = []
            for rec in fw_result.records[:20]:
                row = {"_line_num": rec.get("_line_num"), "_topaz_id": rec.get("_topaz_id")}
                for z in fw_result.field_zones:
                    val = rec.get(z["label"], "")
                    if val:
                        row[z["label"]] = val
                sample_records.append(row)

            # Auto-detected mapping (user can override)
            auto_mapping = {}
            if fw_result.id_fields:
                auto_mapping["chart_number"] = fw_result.id_fields[0]
            if fw_result.name_fields:
                auto_mapping["patient_name"] = fw_result.name_fields[0]

            return {
                "format": "fixed_width",
                "format_detail": (
                    f"Fixed-width: {fw_result.total_records:,} records x "
                    f"{fw_result.record_width} bytes. Line# = Topaz patient ID."
                ),
                "total_records": fw_result.total_records,
                "field_zones": zones_with_samples,
                "sample_records": sample_records,
                "auto_mapping": auto_mapping,
                "warnings": fw_result.warnings,
            }

    # ── Delimited / XML / other formats ──
    parsed = parse_topaz_export(content, file.filename or "preview")

    # For delimited files, also allow header override
    all_headers = parsed.headers_found[:50]

    return {
        "format": parsed.format_detected,
        "headers_found": all_headers,
        "column_mapping": parsed.column_mapping,
        "total_rows": parsed.total_rows,
        "sample_pairs": parsed.crosswalk_pairs[:20],
        "raw_rows": [r for r in parsed.raw_rows[:15] if r],
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
    from backend.app.parsing.fixed_width_parser import (
        parse_fixed_width_records,
        looks_like_fixed_width,
    )

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1", errors="replace")

    # ── Fixed-width record detection ──
    # .NET server exports use fixed-width records where the LINE NUMBER
    # is the Topaz patient ID. Record #9125 = Topaz patient 9125.
    if looks_like_fixed_width(content_bytes):
        fw_result = parse_fixed_width_records(content_bytes)
        if fw_result.total_records > 0:
            from rapidfuzz import fuzz as rfuzz

            # Load billing records with topaz_id for cross-referencing
            br_result = await db.execute(
                select(
                    BillingRecord.id,
                    BillingRecord.patient_id,
                    BillingRecord.patient_name,
                    BillingRecord.topaz_id,
                    BillingRecord.service_date,
                )
            )
            billing_rows = br_result.all()

            # Build topaz_id lookup: topaz_id -> list of billing records
            topaz_lookup = {}
            for bid, pid, pname, tid, sdate in billing_rows:
                if tid:
                    topaz_lookup.setdefault(str(tid).strip(), []).append({
                        "billing_id": bid,
                        "patient_id": pid,
                        "patient_name": pname,
                        "service_date": str(sdate) if sdate else None,
                    })

            # Build jacket_id lookup too
            jacket_lookup = {}
            for bid, pid, pname, tid, sdate in billing_rows:
                if pid is not None:
                    jacket_lookup.setdefault(str(pid).strip(), []).append({
                        "billing_id": bid,
                        "patient_name": pname,
                        "topaz_id": tid,
                        "service_date": str(sdate) if sdate else None,
                    })

            # Position-based crosswalk: line_num = Topaz patient ID
            # Cross-reference against billing records that have topaz_id set
            position_matches = []
            position_mismatches = []
            position_no_record = []
            name_corroborated = 0
            name_mismatch = 0
            total_checked = 0

            # Only check records at positions matching known topaz_ids
            # to avoid iterating all 61k records unnecessarily
            known_topaz_ids = set(topaz_lookup.keys())

            for rec in fw_result.records:
                topaz_id = rec.get("_topaz_id", "")
                if topaz_id not in known_topaz_ids:
                    continue

                total_checked += 1
                db_records = topaz_lookup[topaz_id]

                # Extract name from the file record (first name field)
                file_name = ""
                for nf in fw_result.name_fields:
                    file_name = rec.get(nf, "")
                    if file_name:
                        break

                # Extract any other useful fields
                file_data = {k: v for k, v in rec.items()
                             if not k.startswith("_") and v}

                # Check name corroboration against each billing record
                best_name_score = 0
                best_db_rec = db_records[0]
                for db_rec in db_records:
                    if file_name and db_rec["patient_name"]:
                        score = rfuzz.token_sort_ratio(
                            file_name.upper().strip(),
                            db_rec["patient_name"].upper().strip(),
                        )
                        if score > best_name_score:
                            best_name_score = score
                            best_db_rec = db_rec

                match_entry = {
                    "topaz_id": topaz_id,
                    "line_num": int(topaz_id),
                    "file_name": file_name or None,
                    "db_patient": best_db_rec["patient_name"],
                    "db_jacket_id": best_db_rec.get("patient_id"),
                    "name_similarity": best_name_score if file_name else None,
                    "file_data": file_data,
                    "db_record_count": len(db_records),
                }

                if not file_name:
                    # No name to corroborate — still a position match
                    position_matches.append(match_entry)
                elif best_name_score >= 70:
                    name_corroborated += 1
                    match_entry["status"] = "corroborated"
                    position_matches.append(match_entry)
                else:
                    name_mismatch += 1
                    match_entry["status"] = "name_mismatch"
                    position_mismatches.append(match_entry)

            # Also check a broader sample: pick some positions that are
            # NOT in our topaz_id lookup, but might match jacket_ids
            jacket_cross_ref = []
            for rec in fw_result.records:
                topaz_id = rec.get("_topaz_id", "")
                if topaz_id in known_topaz_ids:
                    continue
                # Check if the content at this line has ID fields
                # that match jacket_ids
                for id_field in fw_result.id_fields:
                    val = rec.get(id_field, "")
                    if val:
                        try:
                            val = str(int(float(val)))
                        except (ValueError, TypeError):
                            pass
                        if val in jacket_lookup:
                            file_name = ""
                            for nf in fw_result.name_fields:
                                file_name = rec.get(nf, "")
                                if file_name:
                                    break
                            db_rec = jacket_lookup[val][0]
                            name_score = 0
                            if file_name and db_rec["patient_name"]:
                                name_score = rfuzz.token_sort_ratio(
                                    file_name.upper().strip(),
                                    db_rec["patient_name"].upper().strip(),
                                )
                            if len(jacket_cross_ref) < 25:
                                jacket_cross_ref.append({
                                    "line_num": int(topaz_id),
                                    "id_field": id_field,
                                    "id_value": val,
                                    "file_name": file_name or None,
                                    "db_patient": db_rec["patient_name"],
                                    "db_topaz_id": db_rec.get("topaz_id"),
                                    "name_similarity": name_score if file_name else None,
                                })
                            break
                if len(jacket_cross_ref) >= 25:
                    break

            # Summary
            verdict_parts = []
            if name_corroborated > 0:
                verdict_parts.append(
                    f"{name_corroborated} records corroborated by name"
                )
            if name_mismatch > 0:
                verdict_parts.append(
                    f"{name_mismatch} records have name mismatches"
                )
            if position_no_record:
                verdict_parts.append(
                    f"{len(position_no_record)} positions had no DB match"
                )

            return {
                "filename": file.filename,
                "verdict": "fixed_width",
                "verdict_detail": (
                    f"Fixed-width file: {fw_result.total_records:,} records x "
                    f"{fw_result.record_width} bytes. Line number = Topaz patient ID. "
                    f"{total_checked} positions matched billing records. "
                    + ". ".join(verdict_parts)
                ),
                "format_info": fw_result.format_info,
                "total_records": fw_result.total_records,
                "record_width": fw_result.record_width,
                "field_zones": fw_result.field_zones,
                "id_fields": fw_result.id_fields,
                "name_fields": fw_result.name_fields,
                "date_fields": fw_result.date_fields,
                "position_crosswalk": {
                    "total_known_topaz_ids": len(known_topaz_ids),
                    "total_checked": total_checked,
                    "name_corroborated": name_corroborated,
                    "name_mismatch": name_mismatch,
                    "corroboration_rate": (
                        round(name_corroborated / total_checked * 100, 1)
                        if total_checked > 0 else 0
                    ),
                },
                "sample_corroborated": [
                    m for m in position_matches if m.get("status") == "corroborated"
                ][:25],
                "sample_mismatches": position_mismatches[:25],
                "sample_no_name": [
                    m for m in position_matches if m.get("status") is None
                ][:10],
                "jacket_id_cross_ref": jacket_cross_ref,
                "sample_records": fw_result.records[:20],
                "unique_topaz_ids_in_db": len(topaz_lookup),
                "unique_jacket_ids_in_db": len(jacket_lookup),
                "warnings": fw_result.warnings,
            }

    # ── Line-based parsing (delimited or single-value) ──
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
