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
    diagnose_unmatched_claim,
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
    """Run the 13-pass auto-matching engine on all unmatched ERA claims."""
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


@router.get("/diagnose/{era_claim_line_id}")
async def diagnose_claim(
    era_claim_line_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Diagnose WHY a specific ERA claim didn't match.

    Returns the claim data, what passes were tried, closest billing
    record candidates, and specific reasons each candidate was rejected.
    """
    return await diagnose_unmatched_claim(db, era_claim_line_id)


# --- Interactive Match Correction ---


class MatchCorrectionRequest(BaseModel):
    era_claim_line_id: int = Field(..., description="ERA claim line to reassign")
    billing_record_id: int = Field(..., description="Target billing record to match to")
    notes: str | None = Field(None, description="Reason for manual correction")


@router.post("/correct-match")
async def correct_match(
    body: MatchCorrectionRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually reassign an ERA claim line to a different billing record.

    Use this when auto-matching made a wrong assignment or failed to match.
    The old match is removed and the new one is set with confidence 1.0 (manual).
    """
    from backend.app.models.era import ERAClaimLine

    # Get the ERA claim line
    ecl_result = await db.execute(
        select(ERAClaimLine).where(ERAClaimLine.id == body.era_claim_line_id)
    )
    ecl = ecl_result.scalar_one_or_none()
    if not ecl:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="ERA claim line not found")

    # Get the target billing record
    br_result = await db.execute(
        select(BillingRecord).where(BillingRecord.id == body.billing_record_id)
    )
    br = br_result.scalar_one_or_none()
    if not br:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Billing record not found")

    # Remove old match from previous billing record if exists
    old_billing_id = ecl.matched_billing_id
    if old_billing_id:
        old_br_result = await db.execute(
            select(BillingRecord).where(BillingRecord.id == old_billing_id)
        )
        old_br = old_br_result.scalar_one_or_none()
        if old_br and old_br.era_claim_id == ecl.claim_id:
            old_br.era_claim_id = None

    # Set new match
    ecl.matched_billing_id = body.billing_record_id
    ecl.match_confidence = 1.0  # Manual match = full confidence

    # Update billing record with ERA data
    br.era_claim_id = ecl.claim_id
    if ecl.paid_amount is not None and float(br.total_payment or 0) == 0:
        br.total_payment = ecl.paid_amount
    if ecl.cas_reason_code:
        br.denial_reason_code = ecl.cas_reason_code
    # Map claim status to denial status
    status_map = {"4": "DENIED", "22": "DENIED"}
    if ecl.claim_status in status_map:
        br.denial_status = status_map[ecl.claim_status]
    elif ecl.claim_status in ("1", "2", "3"):
        br.denial_status = None  # Paid

    # Store correction metadata
    extra = br.extra_data or {}
    extra["manual_match"] = {
        "corrected_at": str(datetime.utcnow()),
        "era_claim_line_id": ecl.id,
        "old_billing_id": old_billing_id,
        "notes": body.notes,
    }
    br.extra_data = extra

    await db.commit()

    return {
        "status": "corrected",
        "era_claim_line_id": ecl.id,
        "claim_id": ecl.claim_id,
        "old_billing_id": old_billing_id,
        "new_billing_id": body.billing_record_id,
        "patient_name": br.patient_name,
        "confidence": 1.0,
    }


@router.get("/billing-search")
async def billing_search(
    q: str = Query(..., min_length=2, description="Search query — name, chart ID, date, or topaz ID"),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search billing records for manual claim linking.

    Auto-detects query type: digits → ID search, date → date search, text → name search.
    """
    from sqlalchemy import or_, cast, String
    import re

    q = q.strip()
    conditions = []

    # Digit-only → search patient_id, topaz_id
    if re.match(r"^\d+$", q):
        conditions.append(BillingRecord.patient_id.ilike(f"%{q}%"))
        conditions.append(BillingRecord.topaz_id.ilike(f"%{q}%"))
        conditions.append(cast(BillingRecord.id, String) == q)
    # Date-like → search service_date
    elif re.match(r"\d{4}-\d{2}-\d{2}", q):
        from datetime import date as date_cls
        try:
            dt = date_cls.fromisoformat(q)
            conditions.append(BillingRecord.service_date == dt)
        except ValueError:
            pass
    # Text → search patient_name
    if not conditions or not re.match(r"^\d+$", q):
        conditions.append(BillingRecord.patient_name.ilike(f"%{q}%"))
        conditions.append(BillingRecord.patient_name_display.ilike(f"%{q}%"))

    result = await db.execute(
        select(BillingRecord)
        .where(or_(*conditions))
        .order_by(BillingRecord.service_date.desc())
        .limit(limit)
    )
    records = result.scalars().all()

    return {
        "results": [
            {
                "id": r.id,
                "patient_name": r.patient_name,
                "service_date": r.service_date.isoformat() if r.service_date else None,
                "insurance_carrier": r.insurance_carrier,
                "modality": r.modality,
                "total_payment": float(r.total_payment or 0),
                "patient_id": r.patient_id,
                "topaz_id": r.topaz_id,
                "era_claim_id": r.era_claim_id,
            }
            for r in records
        ],
        "total": len(records),
    }


class ManualMatchRequest(BaseModel):
    claim_id: str = Field(..., description="ERA claim_id to search for")
    billing_record_id: int = Field(..., description="Billing record to match to")


@router.post("/manual-match")
async def manual_match_by_claim_id(
    body: ManualMatchRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Match an unmatched ERA claim to a billing record by claim_id.

    For when you know which billing record an ERA claim belongs to
    but auto-matching failed to find it.
    """
    from backend.app.models.era import ERAClaimLine
    from datetime import datetime

    # Find the ERA claim line by claim_id
    ecl_result = await db.execute(
        select(ERAClaimLine).where(
            ERAClaimLine.claim_id == body.claim_id,
            ERAClaimLine.matched_billing_id.is_(None),
        )
    )
    ecl = ecl_result.scalar_one_or_none()
    if not ecl:
        # Check if already matched
        ecl_result2 = await db.execute(
            select(ERAClaimLine).where(ERAClaimLine.claim_id == body.claim_id)
        )
        ecl2 = ecl_result2.scalar_one_or_none()
        if ecl2:
            return {
                "status": "already_matched",
                "claim_id": body.claim_id,
                "matched_billing_id": ecl2.matched_billing_id,
            }
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"ERA claim {body.claim_id} not found")

    # Get billing record
    br_result = await db.execute(
        select(BillingRecord).where(BillingRecord.id == body.billing_record_id)
    )
    br = br_result.scalar_one_or_none()
    if not br:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Billing record not found")

    # Apply match
    ecl.matched_billing_id = body.billing_record_id
    ecl.match_confidence = 1.0
    br.era_claim_id = ecl.claim_id
    if ecl.paid_amount is not None and float(br.total_payment or 0) == 0:
        br.total_payment = ecl.paid_amount
    if ecl.cas_reason_code:
        br.denial_reason_code = ecl.cas_reason_code
    status_map = {"4": "DENIED", "22": "DENIED"}
    if ecl.claim_status in status_map:
        br.denial_status = status_map[ecl.claim_status]

    await db.commit()

    return {
        "status": "matched",
        "claim_id": body.claim_id,
        "billing_record_id": body.billing_record_id,
        "patient_name": br.patient_name,
        "paid_amount": float(ecl.paid_amount or 0),
        "confidence": 1.0,
    }


@router.post("/re-match")
async def trigger_rematch(
    force: bool = Query(False, description="Clear ALL existing matches and re-run from scratch"),
    db: AsyncSession = Depends(get_db),
):
    """
    Re-run the auto-matcher.

    Default: only processes currently unmatched claims.
    With force=true: clears ALL existing matches first and re-runs
    everything from scratch (useful after algorithm improvements).
    """
    from backend.app.models.era import ERAClaimLine

    cleared = 0
    if force:
        # Clear match linkages on ERA claim lines
        r1 = await db.execute(
            update(ERAClaimLine)
            .where(ERAClaimLine.matched_billing_id.is_not(None))
            .values(matched_billing_id=None, match_confidence=None)
        )
        cleared = r1.rowcount
        # Clear back-references on billing records (but preserve topaz_id)
        await db.execute(
            update(BillingRecord)
            .where(BillingRecord.era_claim_id.is_not(None))
            .values(era_claim_id=None)
        )
        await db.flush()
        logger.info(f"Force re-match: cleared {cleared} existing matches")

    result = await run_auto_match(db)
    return {
        "status": "completed",
        "cleared_previous": cleared,
        "match_result": result,
    }


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
        if len(fw_result.name_fields) >= 2:
            auto_mapping["last_name"] = fw_result.name_fields[0]
            auto_mapping["first_name"] = fw_result.name_fields[1]
        elif fw_result.name_fields:
            auto_mapping["patient_name"] = fw_result.name_fields[0]
        if fw_result.date_fields:
            auto_mapping["date_of_birth"] = fw_result.date_fields[0]
        if fw_result.insurance_fields:
            auto_mapping["insurance_number"] = fw_result.insurance_fields[0]
        if fw_result.phone_fields:
            auto_mapping["phone"] = fw_result.phone_fields[0]
        if fw_result.zip_fields:
            auto_mapping["zip_code"] = fw_result.zip_fields[0]
        if fw_result.state_fields:
            auto_mapping["state"] = fw_result.state_fields[0]
        if fw_result.city_fields:
            auto_mapping["city"] = fw_result.city_fields[0]

        parsing_metadata = {
            "field_zones": zones_with_samples,
            "sample_records": sample_records,
            "auto_mapping": auto_mapping,
            "id_fields": fw_result.id_fields,
            "name_fields": fw_result.name_fields,
            "date_fields": fw_result.date_fields,
            "phone_fields": fw_result.phone_fields,
            "zip_fields": fw_result.zip_fields,
            "state_fields": fw_result.state_fields,
            "city_fields": fw_result.city_fields,
            "insurance_fields": fw_result.insurance_fields,
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
      {"chart_number": "id_2", "patient_name": "name_1", "custom_referral": "misc_3"}
    For fixed-width: values are zone labels (id_1, name_1, etc.)
    For delimited: values are header names ("Chart Number", "Patient Name", etc.)

    Recognized roles: chart_number, topaz_id, patient_name, last_name,
      first_name, date_of_birth, phone, city, state, zip_code,
      insurance_number, service_date.

    Custom/TBD roles: any key starting with "custom_" preserves raw data
    for future re-parsing (e.g. "custom_1", "custom_referral_source").

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

    # All recognized patient data roles for extraction
    _PATIENT_ROLES = {
        "chart_number", "topaz_id", "patient_name",
        "last_name", "first_name", "date_of_birth",
        "phone", "city", "state", "zip_code",
        "insurance_number", "service_date", "researcher",
    }
    # Custom/TBD roles: any key starting with "custom_" stores raw data
    # for future re-parsing (e.g. "custom_1", "custom_referral_source")
    _CUSTOM_PREFIX = "custom_"

    if record.format_detected == "fixed_width":
        fw_result = parse_fixed_width_records(content_bytes)

        chart_field = field_mapping.get("chart_number")
        name_field = field_mapping.get("patient_name")
        last_name_field = field_mapping.get("last_name")
        first_name_field = field_mapping.get("first_name")
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

            # Patient name (combined or split)
            if name_field:
                val = rec.get(name_field, "").strip()
                if val:
                    pair["patient_name"] = val
            if last_name_field:
                val = rec.get(last_name_field, "").strip()
                if val:
                    pair["last_name"] = val
            if first_name_field:
                val = rec.get(first_name_field, "").strip()
                if val:
                    pair["first_name"] = val

            # Extract all other patient data fields from mapping
            for role in ("date_of_birth", "phone", "city", "state",
                         "zip_code", "insurance_number", "service_date",
                         "researcher"):
                src_field = field_mapping.get(role)
                if src_field:
                    val = rec.get(src_field, "").strip()
                    if val:
                        pair[role] = val

            # Extract custom/TBD fields (any role starting with "custom_")
            for role, src_field in field_mapping.items():
                if role.startswith(_CUSTOM_PREFIX) and src_field:
                    val = rec.get(src_field, "").strip()
                    if val:
                        pair[role] = val

            # Only include if we have something useful
            if pair.get("chart_number") or pair.get("patient_name") or pair.get("last_name"):
                pairs.append(pair)

    else:
        # Delimited / XML: re-parse and extract using user's header mapping
        parsed = parse_topaz_export(content, record.filename)
        for raw_row in parsed.raw_rows:
            pair = {}
            for role, header_name in field_mapping.items():
                if role in _PATIENT_ROLES or role.startswith(_CUSTOM_PREFIX):
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

    from backend.app.models.patient import Patient

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

    # Load existing patients indexed by jacket+topaz for upsert
    existing_patients_result = await db.execute(select(Patient))
    existing_patients = list(existing_patients_result.scalars().all())
    patient_index: dict[tuple, Patient] = {}
    for p in existing_patients:
        patient_index[(p.jacket_number, p.topaz_number)] = p

    applied = 0
    skipped_no_match = 0
    skipped_already_set = 0
    research_patients = 0
    patients_created = 0
    patients_updated = 0
    updated_ids: set[int] = set()

    for pair in pairs:
        chart_num = pair.get("chart_number")
        topaz_id = pair.get("topaz_id")

        # --- Update BillingRecord.topaz_id (existing logic) ---
        if chart_num and topaz_id:
            candidates = by_chart.get(str(chart_num).strip(), [])
            if not candidates:
                skipped_no_match += 1
            else:
                for br in candidates:
                    if br.id in updated_ids:
                        continue
                    if br.topaz_id and br.topaz_id == topaz_id:
                        skipped_already_set += 1
                        continue
                    if br.topaz_id and br.topaz_id != topaz_id:
                        continue
                    br.topaz_id = str(topaz_id).strip()
                    updated_ids.add(br.id)
                    applied += 1
        elif chart_num and not topaz_id:
            # Research patient — no Topaz ID expected
            research_patients += 1
        elif not chart_num and not topaz_id:
            skipped_no_match += 1

        # --- Upsert Patient record with all demographics ---
        jacket = str(chart_num).strip() if chart_num else None
        topaz = str(topaz_id).strip() if topaz_id else None

        if not jacket and not topaz:
            continue

        # Build patient name from split or combined fields
        last_name = pair.get("last_name")
        first_name = pair.get("first_name")
        if not last_name and pair.get("patient_name"):
            # Try splitting "LAST FIRST" or "LAST, FIRST"
            full = pair["patient_name"]
            if "," in full:
                parts = full.split(",", 1)
                last_name = parts[0].strip()
                first_name = parts[1].strip() if len(parts) > 1 else None
            elif " " in full:
                parts = full.split(None, 1)
                last_name = parts[0].strip()
                first_name = parts[1].strip() if len(parts) > 1 else None
            else:
                last_name = full.strip()

        # Parse DOB
        dob = None
        dob_str = pair.get("date_of_birth")
        if dob_str:
            from backend.app.parsing.fixed_width_parser import _parse_date
            parsed_dob = _parse_date(dob_str)
            if parsed_dob:
                from datetime import date as date_type
                try:
                    dob = date_type.fromisoformat(parsed_dob)
                except ValueError:
                    pass

        # Research patient detection
        researcher_name = pair.get("researcher")
        is_research = bool(researcher_name) or (not topaz_id and jacket)

        # Collect custom/TBD fields from the pair
        custom_fields = {
            k: v for k, v in pair.items()
            if k.startswith("custom_") and v
        }

        key = (jacket, topaz)
        existing = patient_index.get(key)

        if existing:
            # Update existing patient with any new data
            changed = False
            for attr, val in [
                ("last_name", last_name),
                ("first_name", first_name),
                ("date_of_birth", dob),
                ("phone", pair.get("phone")),
                ("city", pair.get("city")),
                ("state", pair.get("state")),
                ("zip_code", pair.get("zip_code")),
                ("insurance_number", pair.get("insurance_number")),
                ("is_research", is_research if is_research else None),
                ("researcher", researcher_name),
            ]:
                if val and not getattr(existing, attr):
                    setattr(existing, attr, val)
                    changed = True
            # Merge custom data
            if custom_fields:
                existing_custom = existing.custom_data or {}
                existing_custom.update(custom_fields)
                existing.custom_data = existing_custom
                changed = True
            if changed:
                patients_updated += 1
        else:
            patient = Patient(
                jacket_number=jacket,
                topaz_number=topaz,
                last_name=last_name,
                first_name=first_name,
                date_of_birth=dob,
                phone=pair.get("phone"),
                city=pair.get("city"),
                state=pair.get("state"),
                zip_code=pair.get("zip_code"),
                insurance_number=pair.get("insurance_number"),
                is_research=is_research,
                researcher=researcher_name,
                custom_data=custom_fields if custom_fields else None,
                crosswalk_import_id=import_id,
            )
            db.add(patient)
            patient_index[key] = patient
            patients_created += 1

    from datetime import datetime as dt
    apply_result = {
        "applied": applied,
        "skipped_no_match": skipped_no_match,
        "skipped_already_set": skipped_already_set,
        "research_patients_no_topaz": research_patients,
        "total_pairs": len(pairs),
        "patients_created": patients_created,
        "patients_updated": patients_updated,
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


@router.get("/patients/lookup")
async def lookup_patient(
    jacket_number: str | None = None,
    topaz_number: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Look up a patient by jacket (chart) number or topaz (patient) number.

    Returns all patient data and linked billing records for the identifier.
    Either jacket_number or topaz_number must be provided.
    """
    from backend.app.models.patient import Patient

    if not jacket_number and not topaz_number:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Provide jacket_number or topaz_number query parameter."
        )

    # Find matching patients
    conditions = []
    if jacket_number:
        conditions.append(Patient.jacket_number == jacket_number.strip())
    if topaz_number:
        conditions.append(Patient.topaz_number == topaz_number.strip())

    from sqlalchemy import or_
    result = await db.execute(
        select(Patient).where(or_(*conditions))
    )
    patients = list(result.scalars().all())

    if not patients:
        return {"patients": [], "billing_records": []}

    # Collect all jacket and topaz numbers for billing record lookup
    jacket_nums = {p.jacket_number for p in patients if p.jacket_number}
    topaz_nums = {p.topaz_number for p in patients if p.topaz_number}

    # Find linked billing records
    br_conditions = []
    if jacket_nums:
        # patient_id is Integer, convert jacket numbers
        int_jackets = set()
        for j in jacket_nums:
            try:
                int_jackets.add(int(j))
            except (ValueError, TypeError):
                pass
        if int_jackets:
            br_conditions.append(BillingRecord.patient_id.in_(int_jackets))
    if topaz_nums:
        br_conditions.append(BillingRecord.topaz_id.in_(topaz_nums))

    billing_records = []
    if br_conditions:
        from sqlalchemy import or_ as or_clause
        br_result = await db.execute(
            select(BillingRecord).where(or_clause(*br_conditions))
        )
        billing_records = list(br_result.scalars().all())

    return {
        "patients": [
            {
                "id": p.id,
                "jacket_number": p.jacket_number,
                "topaz_number": p.topaz_number,
                "last_name": p.last_name,
                "first_name": p.first_name,
                "date_of_birth": p.date_of_birth.isoformat() if p.date_of_birth else None,
                "phone": p.phone,
                "city": p.city,
                "state": p.state,
                "zip_code": p.zip_code,
                "insurance_number": p.insurance_number,
                "is_research": p.is_research,
                "researcher": p.researcher,
                "custom_data": p.custom_data,
                "created_at": p.created_at.isoformat() if p.created_at else None,
            }
            for p in patients
        ],
        "billing_records": [
            {
                "id": br.id,
                "patient_name": br.patient_name,
                "patient_id": br.patient_id,
                "topaz_id": br.topaz_id,
                "service_date": br.service_date.isoformat() if br.service_date else None,
                "insurance_carrier": br.insurance_carrier,
                "modality": br.modality,
                "scan_type": br.scan_type,
                "total_payment": float(br.total_payment) if br.total_payment else 0,
                "denial_status": br.denial_status,
            }
            for br in billing_records
        ],
    }


@router.get("/patients/stats")
async def patient_stats(db: AsyncSession = Depends(get_db)):
    """Summary stats for the patient directory."""
    from backend.app.models.patient import Patient
    from sqlalchemy import func

    total = await db.execute(select(func.count(Patient.id)))
    has_jacket = await db.execute(
        select(func.count(Patient.id)).where(Patient.jacket_number.is_not(None))
    )
    has_topaz = await db.execute(
        select(func.count(Patient.id)).where(Patient.topaz_number.is_not(None))
    )
    has_both = await db.execute(
        select(func.count(Patient.id)).where(
            Patient.jacket_number.is_not(None),
            Patient.topaz_number.is_not(None),
        )
    )

    total_count = total.scalar() or 0
    jacket_count = has_jacket.scalar() or 0
    topaz_count = has_topaz.scalar() or 0
    both_count = has_both.scalar() or 0

    return {
        "total_patients": total_count,
        "has_jacket_number": jacket_count,
        "has_topaz_number": topaz_count,
        "has_both_identifiers": both_count,
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


# --- Server Source Management (autonomous .NET file sync) ---


class ServerSourceCreate(BaseModel):
    """Request body for registering a new server source."""
    name: str = Field(..., description="Display name for this source")
    directory_path: str = Field(..., description="Path to .NET server text files")
    poll_interval_minutes: int = Field(60, ge=5, le=1440)


@router.post("/server-sources")
async def register_server_source(
    body: ServerSourceCreate,
    db: AsyncSession = Depends(get_db),
):
    """
    Register a .NET server file directory for autonomous sync.

    After registration, upload a sample file or trigger a preview scan
    to auto-detect fields, then confirm the field mapping. Once mapped,
    the background scheduler will poll for new data automatically.
    """
    import os
    from backend.app.models.server_source import ServerSource

    path = body.directory_path.strip()

    # Validate directory exists and is readable
    if not os.path.isdir(path):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=f"Directory not found: {path}",
        )

    source = ServerSource(
        name=body.name,
        directory_path=path,
        poll_interval_minutes=body.poll_interval_minutes,
        status="PENDING_SETUP",
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)

    # Preview: list files and auto-detect fields from first suitable file
    preview = await _preview_server_directory(path)

    return {
        "id": source.id,
        "name": source.name,
        "directory_path": path,
        "status": source.status,
        "preview": preview,
    }


@router.post("/server-sources/{source_id}/configure")
async def configure_server_source(
    source_id: int,
    field_mapping: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Set the field mapping for a server source and activate it.

    field_mapping example:
      {"chart_number": "id_1", "last_name": "name_1", "first_name": "name_2",
       "date_of_birth": "date_1", "topaz_id": "_line_num"}
    """
    from backend.app.models.server_source import ServerSource

    result = await db.execute(
        select(ServerSource).where(ServerSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Server source not found")

    source.field_mapping = field_mapping
    source.status = "ACTIVE"
    source.last_error = None
    await db.commit()

    return {
        "id": source.id,
        "status": "ACTIVE",
        "field_mapping": field_mapping,
        "message": "Source configured and activated. Background sync will start automatically.",
    }


@router.post("/server-sources/{source_id}/sync")
async def trigger_server_sync(
    source_id: int,
    force_full: bool = False,
    db: AsyncSession = Depends(get_db),
):
    """
    Manually trigger a sync for a server source.

    Set force_full=true to re-process all files regardless of change detection.
    """
    from backend.app.models.server_source import ServerSource
    from backend.app.tasks.server_sync import sync_server_source

    result = await db.execute(
        select(ServerSource).where(ServerSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Server source not found")

    if not source.field_mapping:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Source not configured. Set field mapping first via /configure endpoint.",
        )

    sync_result = await sync_server_source(source, db, force_full=force_full)

    return {
        "id": source.id,
        "name": source.name,
        "sync_result": sync_result,
    }


@router.get("/server-sources")
async def list_server_sources(db: AsyncSession = Depends(get_db)):
    """List all registered server sources."""
    from backend.app.models.server_source import ServerSource

    result = await db.execute(
        select(ServerSource).order_by(ServerSource.created_at.desc())
    )
    sources = list(result.scalars().all())

    return [
        {
            "id": s.id,
            "name": s.name,
            "directory_path": s.directory_path,
            "status": s.status,
            "enabled": s.enabled,
            "poll_interval_minutes": s.poll_interval_minutes,
            "total_files_processed": s.total_files_processed,
            "total_records_imported": s.total_records_imported,
            "last_sync_at": s.last_sync_at.isoformat() if s.last_sync_at else None,
            "last_sync_result": s.last_sync_result,
            "last_error": s.last_error,
            "field_mapping": s.field_mapping,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in sources
    ]


@router.get("/server-sources/{source_id}")
async def get_server_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
):
    """View a server source with full details including file states."""
    from backend.app.models.server_source import ServerSource

    result = await db.execute(
        select(ServerSource).where(ServerSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Server source not found")

    return {
        "id": source.id,
        "name": source.name,
        "directory_path": source.directory_path,
        "status": source.status,
        "enabled": source.enabled,
        "poll_interval_minutes": source.poll_interval_minutes,
        "field_mapping": source.field_mapping,
        "file_states": source.file_states,
        "total_files_processed": source.total_files_processed,
        "total_records_imported": source.total_records_imported,
        "last_sync_at": source.last_sync_at.isoformat() if source.last_sync_at else None,
        "last_sync_result": source.last_sync_result,
        "last_error": source.last_error,
        "created_at": source.created_at.isoformat() if source.created_at else None,
    }


@router.post("/server-sources/{source_id}/preview")
async def preview_server_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Scan the server directory and auto-detect fields from the first file.

    Returns detected field zones with sample values and suggested mapping,
    so the user can confirm or adjust before activating.
    """
    from backend.app.models.server_source import ServerSource

    result = await db.execute(
        select(ServerSource).where(ServerSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Server source not found")

    preview = await _preview_server_directory(source.directory_path)

    return {
        "id": source.id,
        "name": source.name,
        "preview": preview,
    }


@router.patch("/server-sources/{source_id}")
async def update_server_source(
    source_id: int,
    updates: dict,
    db: AsyncSession = Depends(get_db),
):
    """Update server source settings (enable/disable, change interval, etc.)."""
    from backend.app.models.server_source import ServerSource

    result = await db.execute(
        select(ServerSource).where(ServerSource.id == source_id)
    )
    source = result.scalar_one_or_none()
    if not source:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Server source not found")

    allowed = {"enabled", "poll_interval_minutes", "name", "directory_path"}
    for key, val in updates.items():
        if key in allowed:
            setattr(source, key, val)

    await db.commit()

    return {"id": source.id, "status": source.status, "updated": list(updates.keys())}


async def _preview_server_directory(directory: str) -> dict:
    """Scan a directory and auto-detect fields from the first fixed-width file."""
    import os
    from backend.app.parsing.fixed_width_parser import (
        looks_like_fixed_width,
        parse_fixed_width_records,
    )

    files = []
    auto_mapping = {}
    field_zones = []
    sample_records = []

    try:
        entries = sorted(os.listdir(directory))
    except (OSError, PermissionError) as e:
        return {"error": str(e), "files": []}

    for entry in entries:
        filepath = os.path.join(directory, entry)
        if not os.path.isfile(filepath):
            continue
        stat = os.stat(filepath)
        files.append({
            "name": entry,
            "size_bytes": stat.st_size,
            "modified": stat.st_mtime,
        })

    # Auto-detect from first suitable file
    for f_info in files:
        filepath = os.path.join(directory, f_info["name"])
        if not _should_process_preview(f_info["name"]):
            continue
        try:
            with open(filepath, "rb") as f:
                content_bytes = f.read()

            # Strip null bytes
            try:
                text = content_bytes.decode("utf-8")
            except UnicodeDecodeError:
                text = content_bytes.decode("latin-1", errors="replace")
            content_clean = text.replace("\x00", "").encode("utf-8")

            if not looks_like_fixed_width(content_clean):
                continue

            fw_result = parse_fixed_width_records(content_clean)
            if fw_result.total_records == 0:
                continue

            # Build auto-mapping suggestion
            if fw_result.id_fields:
                auto_mapping["chart_number"] = fw_result.id_fields[0]
            if len(fw_result.name_fields) >= 2:
                auto_mapping["last_name"] = fw_result.name_fields[0]
                auto_mapping["first_name"] = fw_result.name_fields[1]
            elif fw_result.name_fields:
                auto_mapping["patient_name"] = fw_result.name_fields[0]
            if fw_result.date_fields:
                auto_mapping["date_of_birth"] = fw_result.date_fields[0]
            if fw_result.insurance_fields:
                auto_mapping["insurance_number"] = fw_result.insurance_fields[0]
            if fw_result.phone_fields:
                auto_mapping["phone"] = fw_result.phone_fields[0]
            if fw_result.zip_fields:
                auto_mapping["zip_code"] = fw_result.zip_fields[0]
            if fw_result.state_fields:
                auto_mapping["state"] = fw_result.state_fields[0]
            if fw_result.city_fields:
                auto_mapping["city"] = fw_result.city_fields[0]
            # Default: line number = topaz ID for .NET server exports
            auto_mapping["topaz_id"] = "_line_num"

            # Build zone info with expanded samples
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
            field_zones = zones_with_samples

            # Sample records
            for rec in fw_result.records[:15]:
                row = {"_line_num": rec.get("_line_num")}
                for z in fw_result.field_zones:
                    val = rec.get(z["label"], "")
                    if val:
                        row[z["label"]] = val
                sample_records.append(row)

            f_info["detected"] = True
            f_info["record_width"] = fw_result.record_width
            f_info["total_records"] = fw_result.total_records
            break  # Only need first file for detection

        except Exception as e:
            f_info["error"] = str(e)
            continue

    return {
        "files": files[:50],
        "auto_mapping": auto_mapping,
        "field_zones": field_zones,
        "sample_records": sample_records,
    }


@router.post("/crosswalk/re-extract/{import_id}")
async def re_extract_crosswalk(
    import_id: int,
    field_mapping: dict,
    db: AsyncSession = Depends(get_db),
):
    """
    Re-parse a previously imported file with a new field mapping.

    Raw data is preserved in the database, so you can re-extract
    with different roles at any time — including new custom_ TBD fields.
    Resets status back to MAPPED and overwrites previous extraction.
    """
    from backend.app.models.crosswalk_import import CrosswalkImport

    result = await db.execute(
        select(CrosswalkImport).where(CrosswalkImport.id == import_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Import not found")

    if not record.raw_content:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="No raw content stored for this import. Cannot re-extract."
        )

    # Reset status so it can be re-applied
    record.status = "UPLOADED"
    record.extracted_pairs = None
    record.extracted_count = None
    record.applied_count = None
    record.apply_result = None
    record.applied_at = None
    await db.commit()

    # Re-run the extract step with the new mapping
    return await extract_crosswalk_pairs(import_id, field_mapping, db)


@router.post("/crosswalk/re-import/{import_id}")
async def re_import_crosswalk(
    import_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Re-apply a previously extracted crosswalk import.

    Use this after re-extracting with updated field mappings, or to
    retry applying after fixing billing data issues. Resets applied
    status and re-runs the apply step.
    """
    from backend.app.models.crosswalk_import import CrosswalkImport

    result = await db.execute(
        select(CrosswalkImport).where(CrosswalkImport.id == import_id)
    )
    record = result.scalar_one_or_none()
    if not record:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Import not found")

    if not record.extracted_pairs:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="No extracted pairs. Run extract step first."
        )

    # Reset apply status so it can be re-applied
    record.status = "MAPPED"
    record.applied_count = None
    record.apply_result = None
    record.applied_at = None
    await db.commit()

    # Re-run the apply step
    return await apply_crosswalk_import(import_id, db)


def _should_process_preview(filename: str) -> bool:
    """Check if a file should be previewed."""
    from pathlib import Path
    ext = Path(filename).suffix.lower()
    return ext in {"", ".txt", ".dat", ".bin", ".raw", ".exp"}
