"""API routes for auto-matching, crosswalk, and match review."""

import logging
from fastapi import APIRouter, Depends, File, Query, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select, update, func, delete
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


@router.post("/crosswalk/propagate")
async def crosswalk_propagate():
    """Disabled — topaz_id assignment now only comes from user-approved crosswalk imports."""
    return {
        "status": "disabled",
        "message": (
            "Automatic topaz_id propagation has been disabled. "
            "Use the 3-step crosswalk import flow instead: "
            "upload-raw → extract → apply."
        ),
    }


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


# --- Topaz Export Crosswalk (3-step: Upload → Map/Extract → Apply) ---

@router.post("/crosswalk/upload-raw")
async def upload_raw_crosswalk(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """
    Step 1: Upload a raw data file and store it for examination.

    Detects format, extracts field zones / headers and sample values.
    Does NOT parse crosswalk pairs or modify billing records.
    Returns the import ID for subsequent extract and apply steps.
    """
    from backend.app.models.crosswalk_import import CrosswalkImport
    from backend.app.parsing.fixed_width_parser import (
        looks_like_fixed_width,
        parse_fixed_width_records,
    )

    content_bytes = await file.read()
    try:
        content = content_bytes.decode("utf-8")
    except UnicodeDecodeError:
        content = content_bytes.decode("latin-1", errors="replace")

    # Strip null bytes — .NET binary files often contain 0x00 padding
    # which PostgreSQL TEXT columns reject
    content = content.replace("\x00", "")

    filename = file.filename or "upload"
    parsing_metadata = {}
    format_detected = "unknown"
    format_detail = ""
    total_records = 0

    # ── Detect format and gather metadata for user review ──
    if looks_like_fixed_width(content_bytes):
        fw_result = parse_fixed_width_records(content_bytes)
        format_detected = "fixed_width"
        format_detail = (
            f"Fixed-width: {fw_result.total_records:,} records x "
            f"{fw_result.record_width} bytes"
        )
        total_records = fw_result.total_records

        # Build expanded sample values for each zone
        zones_with_samples = []
        for z in fw_result.field_zones:
            samples = []
            for rec in fw_result.records[:50]:
                val = rec.get(z["label"], "")
                if val and val not in samples:
                    samples.append(val)
                if len(samples) >= 8:
                    break
            zones_with_samples.append({**z, "sample_values": samples})

        # Sample records for display
        sample_records = []
        for rec in fw_result.records[:25]:
            row = {"_line_num": rec.get("_line_num")}
            for z in fw_result.field_zones:
                val = rec.get(z["label"], "")
                if val:
                    row[z["label"]] = val
            sample_records.append(row)

        # Auto-suggested mapping (user will override)
        auto_mapping = {}
        if fw_result.id_fields:
            auto_mapping["chart_number"] = fw_result.id_fields[0]
        if fw_result.name_fields:
            auto_mapping["patient_name"] = fw_result.name_fields[0]

        parsing_metadata = {
            "field_zones": zones_with_samples,
            "sample_records": sample_records,
            "auto_mapping": auto_mapping,
            "id_fields": fw_result.id_fields,
            "name_fields": fw_result.name_fields,
            "date_fields": fw_result.date_fields,
            "record_width": fw_result.record_width,
            "warnings": fw_result.warnings,
        }
    else:
        # Delimited / XML
        parsed = parse_topaz_export(content, filename)
        format_detected = parsed.format_detected
        total_records = parsed.total_rows
        format_detail = f"{format_detected}: {total_records:,} rows"

        parsing_metadata = {
            "headers": parsed.headers_found[:50],
            "auto_mapping": parsed.column_mapping,
            "sample_rows": [r for r in parsed.raw_rows[:25] if r],
            "warnings": parsed.warnings,
        }

    # Store in database
    record = CrosswalkImport(
        filename=filename,
        file_size_bytes=len(content_bytes),
        raw_content=content,
        format_detected=format_detected,
        format_detail=format_detail,
        total_records=total_records,
        parsing_metadata=parsing_metadata,
        status="UPLOADED",
    )
    db.add(record)
    await db.commit()
    await db.refresh(record)

    return {
        "id": record.id,
        "status": "UPLOADED",
        "filename": filename,
        "format": format_detected,
        "format_detail": format_detail,
        "total_records": total_records,
        "parsing_metadata": parsing_metadata,
    }


@router.post("/crosswalk/extract/{import_id}")
async def extract_crosswalk_pairs(
    import_id: int,
    field_mapping: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 2: User assigns field roles, system extracts crosswalk pairs.

    field_mapping example:
      {"chart_number": "id_2", "patient_name": "name_1"}
    For fixed-width: values are zone labels (id_1, name_1, etc.)
    For delimited: values are header names ("Chart Number", "Patient Name", etc.)

    Returns extracted pairs for review. Does NOT modify billing records.
    """
    from backend.app.models.crosswalk_import import CrosswalkImport
    from backend.app.parsing.fixed_width_parser import (
        looks_like_fixed_width,
        parse_fixed_width_records,
    )

    result = await db.execute(
        select(CrosswalkImport).where(CrosswalkImport.id == import_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Import not found")

    content = record.raw_content
    content_bytes = content.encode("utf-8", errors="replace")
    pairs = []

    if record.format_detected == "fixed_width":
        fw_result = parse_fixed_width_records(content_bytes)

        chart_field = field_mapping.get("chart_number")
        name_field = field_mapping.get("patient_name")
        # For fixed-width, line number can be the topaz_id if user says so
        use_line_as_topaz = field_mapping.get("topaz_id") == "_line_num"
        topaz_field = field_mapping.get("topaz_id") if not use_line_as_topaz else None

        for rec in fw_result.records:
            pair = {"_line_num": rec.get("_line_num")}

            # Topaz ID: either from line number or a specific field
            if use_line_as_topaz or not topaz_field:
                pair["topaz_id"] = str(rec.get("_line_num", ""))
            elif topaz_field:
                val = rec.get(topaz_field, "").strip()
                pair["topaz_id"] = val if val else None

            # Chart/Jacket number
            if chart_field:
                val = rec.get(chart_field, "").strip()
                if val:
                    try:
                        pair["chart_number"] = str(int(float(val)))
                    except (ValueError, TypeError):
                        pair["chart_number"] = val

            # Patient name
            if name_field:
                val = rec.get(name_field, "").strip()
                if val:
                    pair["patient_name"] = val

            # Only include if we have something useful
            if pair.get("chart_number") or pair.get("patient_name"):
                pairs.append(pair)

    else:
        # Delimited / XML: re-parse and extract using user's header mapping
        parsed = parse_topaz_export(content, record.filename)
        for raw_row in parsed.raw_rows:
            pair = {}
            for role, header_name in field_mapping.items():
                if role in ("chart_number", "topaz_id", "patient_name", "service_date"):
                    val = str(raw_row.get(header_name, "")).strip()
                    if val:
                        pair[role] = val
            if pair.get("chart_number") or pair.get("topaz_id"):
                pairs.append(pair)

    # Validate: check how many chart_numbers actually exist in billing_records
    chart_numbers_in_file = {p["chart_number"] for p in pairs if p.get("chart_number")}
    validation = {"total_extracted": len(pairs)}

    if chart_numbers_in_file:
        br_result = await db.execute(
            select(BillingRecord.patient_id)
            .where(BillingRecord.patient_id.is_not(None))
            .distinct()
        )
        db_chart_numbers = {str(r[0]).strip() for r in br_result.all()}
        matched = chart_numbers_in_file & db_chart_numbers
        validation["chart_numbers_in_file"] = len(chart_numbers_in_file)
        validation["chart_numbers_found_in_db"] = len(matched)
        validation["chart_numbers_not_in_db"] = len(chart_numbers_in_file - db_chart_numbers)

    # Save to record
    from datetime import datetime as dt
    record.field_mapping = field_mapping
    record.extracted_pairs = pairs[:50000]  # Cap storage
    record.extracted_count = len(pairs)
    record.status = "MAPPED"
    record.mapped_at = dt.utcnow()
    await db.commit()

    return {
        "id": import_id,
        "status": "MAPPED",
        "field_mapping": field_mapping,
        "extracted_count": len(pairs),
        "sample_pairs": pairs[:30],
        "validation": validation,
    }


@router.post("/crosswalk/apply/{import_id}")
async def apply_crosswalk_import(
    import_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Step 3: User approves — apply extracted pairs to billing records.

    Only updates BillingRecord.topaz_id where chart_number matches
    patient_id exactly. No fuzzy matching. No guessing.
    """
    from backend.app.models.crosswalk_import import CrosswalkImport

    result = await db.execute(
        select(CrosswalkImport).where(CrosswalkImport.id == import_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Import not found")

    if record.status == "APPLIED":
        return {
            "id": import_id,
            "status": "ALREADY_APPLIED",
            "message": "This import was already applied.",
            "apply_result": record.apply_result,
        }

    if not record.extracted_pairs:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="No extracted pairs. Run extract step first."
        )

    pairs = record.extracted_pairs

    # Load billing records that need topaz_id, indexed by patient_id
    br_result = await db.execute(
        select(BillingRecord).where(BillingRecord.patient_id.is_not(None))
    )
    all_billing = list(br_result.scalars().all())

    by_chart: dict[str, list] = {}
    for br in all_billing:
        key = str(br.patient_id).strip()
        by_chart.setdefault(key, []).append(br)

    applied = 0
    skipped_no_match = 0
    skipped_already_set = 0
    updated_ids: set[int] = set()

    for pair in pairs:
        chart_num = pair.get("chart_number")
        topaz_id = pair.get("topaz_id")
        if not chart_num or not topaz_id:
            skipped_no_match += 1
            continue

        candidates = by_chart.get(str(chart_num).strip(), [])
        if not candidates:
            skipped_no_match += 1
            continue

        for br in candidates:
            if br.id in updated_ids:
                continue
            if br.topaz_id and br.topaz_id == topaz_id:
                skipped_already_set += 1
                continue
            if br.topaz_id and br.topaz_id != topaz_id:
                # Don't overwrite existing different topaz_id
                continue
            br.topaz_id = str(topaz_id).strip()
            updated_ids.add(br.id)
            applied += 1

    if applied > 0:
        await db.commit()

    from datetime import datetime as dt
    apply_result = {
        "applied": applied,
        "skipped_no_match": skipped_no_match,
        "skipped_already_set": skipped_already_set,
        "total_pairs": len(pairs),
    }
    record.applied_count = applied
    record.apply_result = apply_result
    record.status = "APPLIED"
    record.applied_at = dt.utcnow()
    await db.commit()

    return {
        "id": import_id,
        "status": "APPLIED",
        "apply_result": apply_result,
    }


@router.get("/crosswalk/imports")
async def list_crosswalk_imports(db: AsyncSession = Depends(get_db)):
    """List all past crosswalk imports."""
    from backend.app.models.crosswalk_import import CrosswalkImport

    result = await db.execute(
        select(CrosswalkImport).order_by(CrosswalkImport.created_at.desc())
    )
    records = result.scalars().all()
    return [
        {
            "id": r.id,
            "filename": r.filename,
            "format": r.format_detected,
            "total_records": r.total_records,
            "extracted_count": r.extracted_count,
            "applied_count": r.applied_count,
            "status": r.status,
            "field_mapping": r.field_mapping,
            "created_at": r.created_at.isoformat() if r.created_at else None,
            "applied_at": r.applied_at.isoformat() if r.applied_at else None,
        }
        for r in records
    ]


@router.get("/crosswalk/imports/{import_id}")
async def get_crosswalk_import(
    import_id: int,
    db: AsyncSession = Depends(get_db),
):
    """View a stored crosswalk import with raw data, mapping, and results."""
    from backend.app.models.crosswalk_import import CrosswalkImport

    result = await db.execute(
        select(CrosswalkImport).where(CrosswalkImport.id == import_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Import not found")

    return {
        "id": record.id,
        "filename": record.filename,
        "format": record.format_detected,
        "format_detail": record.format_detail,
        "total_records": record.total_records,
        "status": record.status,
        "parsing_metadata": record.parsing_metadata,
        "field_mapping": record.field_mapping,
        "extracted_count": record.extracted_count,
        "sample_pairs": record.extracted_pairs[:30] if record.extracted_pairs else [],
        "applied_count": record.applied_count,
        "apply_result": record.apply_result,
        "created_at": record.created_at.isoformat() if record.created_at else None,
        "mapped_at": record.mapped_at.isoformat() if record.mapped_at else None,
        "applied_at": record.applied_at.isoformat() if record.applied_at else None,
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


# --- Database Reset ---

@router.get("/reset/preview")
async def reset_preview(db: AsyncSession = Depends(get_db)):
    """Preview what a reset would clear — shows counts for each table."""
    from backend.app.models.crosswalk_import import CrosswalkImport
    from backend.app.models.era import ERAPayment, ERAClaimLine
    from backend.app.models.import_file import ImportFile

    total_billing = (await db.execute(func.count(BillingRecord.id))).scalar() or 0
    with_topaz = (await db.execute(
        select(func.count(BillingRecord.id)).where(BillingRecord.topaz_id.is_not(None))
    )).scalar() or 0
    with_era = (await db.execute(
        select(func.count(BillingRecord.id)).where(BillingRecord.era_claim_id.is_not(None))
    )).scalar() or 0
    total_era_payments = (await db.execute(select(func.count(ERAPayment.id)))).scalar() or 0
    total_era_claims = (await db.execute(select(func.count(ERAClaimLine.id)))).scalar() or 0
    total_crosswalk = (await db.execute(select(func.count(CrosswalkImport.id)))).scalar() or 0
    total_imports = (await db.execute(select(func.count(ImportFile.id)))).scalar() or 0

    return {
        "billing_records": total_billing,
        "billing_with_topaz_id": with_topaz,
        "billing_with_era_claim_id": with_era,
        "era_payments": total_era_payments,
        "era_claim_lines": total_era_claims,
        "crosswalk_imports": total_crosswalk,
        "import_files": total_imports,
    }


class ResetRequest(BaseModel):
    clear_topaz_ids: bool = False
    clear_era_matches: bool = False
    clear_era_data: bool = False
    clear_billing_records: bool = False
    clear_crosswalk_imports: bool = False
    confirm: str = ""


@router.post("/reset/execute")
async def reset_execute(
    body: ResetRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Clear selected data from the database for a clean reimport.

    Requires confirm="RESET" to proceed.
    """
    if body.confirm != "RESET":
        return {"status": "error", "message": "Set confirm to 'RESET' to proceed."}

    from backend.app.models.crosswalk_import import CrosswalkImport
    from backend.app.models.era import ERAPayment, ERAClaimLine
    from backend.app.models.import_file import ImportFile

    results = {}

    # Clear topaz_id from billing records (undo bad crosswalk assignments)
    if body.clear_topaz_ids:
        r = await db.execute(
            update(BillingRecord)
            .where(BillingRecord.topaz_id.is_not(None))
            .values(topaz_id=None)
        )
        results["topaz_ids_cleared"] = r.rowcount

    # Clear ERA match linkages on billing records
    if body.clear_era_matches:
        r = await db.execute(
            update(BillingRecord)
            .where(BillingRecord.era_claim_id.is_not(None))
            .values(era_claim_id=None, denial_status=None, denial_reason_code=None)
        )
        results["era_matches_cleared"] = r.rowcount
        # Also clear match linkages on ERA claim lines
        r2 = await db.execute(
            update(ERAClaimLine)
            .where(ERAClaimLine.matched_billing_id.is_not(None))
            .values(matched_billing_id=None, match_confidence=None)
        )
        results["era_claim_links_cleared"] = r2.rowcount

    # Delete all ERA data (payments + claim lines)
    if body.clear_era_data:
        r1 = await db.execute(delete(ERAClaimLine))
        r2 = await db.execute(delete(ERAPayment))
        results["era_claim_lines_deleted"] = r1.rowcount
        results["era_payments_deleted"] = r2.rowcount

    # Delete all billing records (full wipe for reimport)
    if body.clear_billing_records:
        r = await db.execute(delete(BillingRecord))
        results["billing_records_deleted"] = r.rowcount
        # Also clear import file tracking
        r2 = await db.execute(delete(ImportFile))
        results["import_files_deleted"] = r2.rowcount

    # Delete crosswalk import history
    if body.clear_crosswalk_imports:
        r = await db.execute(delete(CrosswalkImport))
        results["crosswalk_imports_deleted"] = r.rowcount

    await db.commit()

    return {"status": "success", "results": results}
