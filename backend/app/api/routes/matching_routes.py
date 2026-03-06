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
    # Check if this is a fixed-width record file (e.g., 128-byte .NET exports)
    if looks_like_fixed_width(content_bytes):
        fw_result = parse_fixed_width_records(content_bytes)
        if fw_result.total_records > 0:
            # Load billing records for cross-referencing
            br_result = await db.execute(
                select(
                    BillingRecord.patient_id,
                    BillingRecord.patient_name,
                    BillingRecord.topaz_id,
                    BillingRecord.service_date,
                ).where(BillingRecord.patient_id.is_not(None))
            )
            billing_rows = br_result.all()

            jacket_lookup = {}
            for pid, pname, tid, sdate in billing_rows:
                jacket_lookup.setdefault(str(pid).strip(), []).append({
                    "patient_name": pname, "topaz_id": tid,
                    "service_date": str(sdate) if sdate else None,
                })
            topaz_lookup = {}
            for pid, pname, tid, sdate in billing_rows:
                if tid:
                    topaz_lookup.setdefault(str(tid).strip(), []).append({
                        "patient_id": pid, "patient_name": pname,
                        "service_date": str(sdate) if sdate else None,
                    })

            # Also load names for name-based cross-referencing
            name_result = await db.execute(
                select(
                    BillingRecord.patient_name,
                    BillingRecord.patient_id,
                    BillingRecord.topaz_id,
                ).where(BillingRecord.patient_name.is_not(None))
            )
            name_rows = name_result.all()
            name_lookup = {}
            for pname, pid, tid in name_rows:
                key = pname.upper().strip() if pname else ""
                if key:
                    name_lookup.setdefault(key, []).append({
                        "patient_id": pid, "topaz_id": tid,
                    })

            # Cross-reference each ID field's values against billing records
            from rapidfuzz import fuzz as rfuzz
            field_cross_ref = {}
            for zone in fw_result.field_zones:
                label = zone["label"]
                if not label.startswith("id_") and not label.startswith("name_"):
                    continue

                jacket_hits = 0
                topaz_hits = 0
                name_hits = 0
                sample_matches = []
                checked = 0

                for rec in fw_result.records[:2000]:
                    val = rec.get(label, "")
                    if not val:
                        continue
                    checked += 1

                    if label.startswith("id_"):
                        # Try numeric ID matching
                        test_val = val.strip()
                        try:
                            test_val = str(int(float(test_val)))
                        except (ValueError, TypeError):
                            pass

                        if test_val in jacket_lookup:
                            jacket_hits += 1
                            recs = jacket_lookup[test_val]
                            if len(sample_matches) < 15:
                                # Cross-verify: check if ANY name field in same
                                # record matches the patient name
                                name_corroboration = None
                                for nf in fw_result.name_fields:
                                    name_val = rec.get(nf, "")
                                    if name_val:
                                        best_name_score = 0
                                        for r in recs:
                                            ns = rfuzz.token_sort_ratio(
                                                name_val.upper(),
                                                (r["patient_name"] or "").upper()
                                            )
                                            best_name_score = max(best_name_score, ns)
                                        name_corroboration = {
                                            "file_name": name_val,
                                            "db_name": recs[0]["patient_name"],
                                            "similarity": best_name_score,
                                        }
                                        break
                                sample_matches.append({
                                    "value": test_val,
                                    "match_type": "jacket_id",
                                    "patient": recs[0]["patient_name"],
                                    "topaz_id": recs[0]["topaz_id"],
                                    "name_corroboration": name_corroboration,
                                })
                        elif test_val in topaz_lookup:
                            topaz_hits += 1
                            recs = topaz_lookup[test_val]
                            if len(sample_matches) < 15:
                                name_corroboration = None
                                for nf in fw_result.name_fields:
                                    name_val = rec.get(nf, "")
                                    if name_val:
                                        best_name_score = 0
                                        for r in recs:
                                            ns = rfuzz.token_sort_ratio(
                                                name_val.upper(),
                                                (r["patient_name"] or "").upper()
                                            )
                                            best_name_score = max(best_name_score, ns)
                                        name_corroboration = {
                                            "file_name": name_val,
                                            "db_name": recs[0]["patient_name"],
                                            "similarity": best_name_score,
                                        }
                                        break
                                sample_matches.append({
                                    "value": test_val,
                                    "match_type": "topaz_id",
                                    "patient": recs[0]["patient_name"],
                                    "jacket_id": recs[0].get("patient_id"),
                                    "name_corroboration": name_corroboration,
                                })

                    elif label.startswith("name_"):
                        # Name field — try matching against billing names
                        name_upper = val.upper().strip()
                        if name_upper in name_lookup:
                            name_hits += 1
                            if len(sample_matches) < 15:
                                sample_matches.append({
                                    "value": val,
                                    "match_type": "exact_name",
                                    "jacket_id": name_lookup[name_upper][0].get("patient_id"),
                                    "topaz_id": name_lookup[name_upper][0].get("topaz_id"),
                                })
                        else:
                            # Fuzzy name match
                            best_match = None
                            best_score = 0
                            for db_name in list(name_lookup.keys())[:500]:
                                score = rfuzz.token_sort_ratio(name_upper, db_name)
                                if score > best_score:
                                    best_score = score
                                    best_match = db_name
                            if best_score >= 85:
                                name_hits += 1
                                if len(sample_matches) < 15:
                                    sample_matches.append({
                                        "value": val,
                                        "match_type": "fuzzy_name",
                                        "db_name": best_match,
                                        "similarity": best_score,
                                        "jacket_id": name_lookup.get(best_match, [{}])[0].get("patient_id"),
                                    })

                total_hits = jacket_hits + topaz_hits + name_hits
                field_cross_ref[label] = {
                    "zone": zone,
                    "checked": checked,
                    "jacket_id_hits": jacket_hits,
                    "topaz_id_hits": topaz_hits,
                    "name_hits": name_hits,
                    "total_hits": total_hits,
                    "hit_rate": round(total_hits / checked * 100, 1) if checked > 0 else 0,
                    "sample_matches": sample_matches,
                }

            return {
                "filename": file.filename,
                "verdict": "fixed_width",
                "verdict_detail": (
                    f"Fixed-width record file detected. "
                    f"{fw_result.total_records} records x {fw_result.record_width} bytes/record. "
                    f"{len(fw_result.field_zones)} field zones discovered."
                ),
                "format_info": fw_result.format_info,
                "total_records": fw_result.total_records,
                "record_width": fw_result.record_width,
                "field_zones": fw_result.field_zones,
                "id_fields": fw_result.id_fields,
                "name_fields": fw_result.name_fields,
                "date_fields": fw_result.date_fields,
                "field_cross_reference": field_cross_ref,
                "sample_records": fw_result.records[:20],
                "unique_jacket_ids_in_db": len(jacket_lookup),
                "unique_topaz_ids_in_db": len(topaz_lookup),
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
