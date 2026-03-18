"""F-04: Denial Tracking & Appeal Queue.

Identifies all claims where total_payment=0 OR ERA CLP02=4 (denied).
Queue sorted by recoverability_score = billed_amount * (1 - days_old/365).
Tracks status: DENIED -> APPEALED -> RESOLVED / WRITTEN_OFF.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select, func, case, update, or_, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAClaimLine, ERAPayment
from backend.app.analytics.public_code_tables import CARC_CODES
from backend.app.revenue.denial_actions import get_denial_detail, CAS_GROUP_CONTEXT
from backend.app.revenue.writeoff_filter import not_written_off, is_written_off, TERMINAL_STATUSES


def _recoverability_score(billed: float | None, service_date: date | None) -> float:
    """recoverability_score = billed_amount * (1 - days_old/365)."""
    if not billed or not service_date:
        return 0.0
    days_old = (date.today() - service_date).days
    if days_old < 0:
        days_old = 0
    score = float(billed) * max(0.0, 1.0 - days_old / 365.0)
    return round(score, 2)


def _serialize_denial(row: BillingRecord, era_info: dict | None = None) -> dict:
    billed = float(era_info.get("billed_amount") or 0) if era_info else 0
    if billed == 0:
        billed = float(row.total_payment or 0) + float(row.extra_charges or 0)

    days_old = (date.today() - row.service_date).days if row.service_date else None
    carc = era_info.get("cas_reason_code") if era_info else row.denial_reason_code
    cas_group = era_info.get("cas_group_code") if era_info else None
    adjustment = era_info.get("cas_adjustment_amount") if era_info else None

    # Get action suggestion
    action = get_denial_detail(
        carc_code=carc,
        cas_group=cas_group,
        billed_amount=billed,
        paid_amount=float(row.total_payment or 0),
        adjustment_amount=float(adjustment or 0),
        days_old=days_old or 0,
        carrier=row.insurance_carrier,
    )

    return {
        "id": row.id,
        "patient_name": row.patient_name,
        "patient_id": row.patient_id,
        "topaz_id": row.topaz_id,
        "service_date": str(row.service_date) if row.service_date else None,
        "insurance_carrier": row.insurance_carrier,
        "modality": row.modality,
        "scan_type": row.scan_type,
        "referring_doctor": row.referring_doctor,
        "total_payment": float(row.total_payment or 0),
        "billed_amount": billed,
        "denial_status": row.denial_status or "DENIED",
        "denial_reason_code": row.denial_reason_code,
        "denial_reason_description": CARC_CODES.get(str(carc), None) if carc else None,
        "era_claim_id": row.era_claim_id,
        "appeal_deadline": str(row.appeal_deadline) if row.appeal_deadline else None,
        "recoverability_score": _recoverability_score(billed, row.service_date),
        "days_old": days_old,
        "cas_group_code": cas_group,
        "cas_group_label": CAS_GROUP_CONTEXT.get(cas_group, {}).get("label") if cas_group else None,
        "cas_reason_code": carc,
        "cas_adjustment_amount": adjustment,
        # Action-oriented fields
        "recommended_action": action["recommended_action"],
        "fix_instructions": action["fix_instructions"],
        "severity": action["severity"],
        "recoverable": action["recoverable"],
        "priority_score": action["priority_score"],
    }


async def get_denials(
    db: AsyncSession,
    status: str | None = None,
    carrier: str | None = None,
    modality: str | None = None,
    sort_by: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """List all denied claims with filters."""
    # Base query: total_payment=0, or denial_status set, or matched to ERA denied claim
    conditions = [
        BillingRecord.total_payment == 0,
        BillingRecord.denial_status.isnot(None),
    ]
    query = select(BillingRecord).where(or_(*conditions))

    # Exclude written-off / resolved unless user explicitly filters by status
    if status:
        query = query.where(BillingRecord.denial_status == status.upper())
    else:
        query = query.where(not_written_off())
    if carrier:
        query = query.where(BillingRecord.insurance_carrier.ilike(f"%{carrier}%"))
    if modality:
        query = query.where(BillingRecord.modality == modality.upper())

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    # Sort
    query = query.order_by(BillingRecord.total_payment.asc(), BillingRecord.service_date.desc())
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    rows = result.scalars().all()

    # Fetch ERA info for matched claims
    era_claim_ids = [r.era_claim_id for r in rows if r.era_claim_id]
    era_map = {}
    if era_claim_ids:
        era_q = select(ERAClaimLine).where(ERAClaimLine.claim_id.in_(era_claim_ids))
        era_result = await db.execute(era_q)
        for ecl in era_result.scalars().all():
            era_map[ecl.claim_id] = {
                "billed_amount": float(ecl.billed_amount or 0),
                "cas_group_code": ecl.cas_group_code,
                "cas_reason_code": ecl.cas_reason_code,
                "cas_adjustment_amount": float(ecl.cas_adjustment_amount or 0) if ecl.cas_adjustment_amount else None,
            }

    denials = [_serialize_denial(r, era_map.get(r.era_claim_id)) for r in rows]

    return {"total": total, "page": page, "per_page": per_page, "denials": denials}


async def get_denial_queue(
    db: AsyncSession,
    limit: int = 50,
) -> dict:
    """Priority appeal queue sorted by recoverability score."""
    conditions = [
        BillingRecord.total_payment == 0,
        BillingRecord.denial_status.isnot(None),
    ]
    # Exclude written-off / resolved / carrier X
    query = select(BillingRecord).where(
        or_(*conditions),
        not_written_off(),
    )

    result = await db.execute(query)
    rows = result.scalars().all()

    # Fetch ERA info
    era_claim_ids = [r.era_claim_id for r in rows if r.era_claim_id]
    era_map = {}
    if era_claim_ids:
        era_q = select(ERAClaimLine).where(ERAClaimLine.claim_id.in_(era_claim_ids))
        era_result = await db.execute(era_q)
        for ecl in era_result.scalars().all():
            era_map[ecl.claim_id] = {
                "billed_amount": float(ecl.billed_amount or 0),
                "cas_group_code": ecl.cas_group_code,
                "cas_reason_code": ecl.cas_reason_code,
                "cas_adjustment_amount": float(ecl.cas_adjustment_amount or 0) if ecl.cas_adjustment_amount else None,
            }

    denials = [_serialize_denial(r, era_map.get(r.era_claim_id)) for r in rows]
    # Sort by recoverability score DESC
    denials.sort(key=lambda d: d["recoverability_score"], reverse=True)

    return {
        "total": len(denials),
        "queue": denials[:limit],
    }


async def get_denial_summary(db: AsyncSession) -> dict:
    """Summary stats for denials. Excludes written-off/resolved/carrier X from active counts."""
    # Active denials only (exclude terminal statuses + carrier X)
    active_base = and_(
        or_(
            BillingRecord.total_payment == 0,
            BillingRecord.denial_status.isnot(None),
        ),
        not_written_off(),
    )

    # Total active denied
    total_q = select(func.count()).where(active_base)
    total_denied = (await db.execute(total_q)).scalar() or 0

    # By status (active only)
    status_col = func.coalesce(BillingRecord.denial_status, "DENIED").label("status")
    status_q = (
        select(
            status_col,
            func.count().label("count"),
        )
        .where(active_base)
        .group_by(status_col)
    )
    status_result = await db.execute(status_q)
    by_status = [{"status": r.status, "count": r.count} for r in status_result]

    # By carrier (active only)
    carrier_q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            func.count().label("count"),
        )
        .where(active_base)
        .group_by(BillingRecord.insurance_carrier)
        .order_by(func.count().desc())
        .limit(10)
    )
    carrier_result = await db.execute(carrier_q)
    by_carrier = [{"carrier": r.carrier, "count": r.count} for r in carrier_result]

    # By denial reason code (active only)
    reason_q = (
        select(
            func.coalesce(BillingRecord.denial_reason_code, "UNKNOWN").label("reason"),
            func.count().label("count"),
        )
        .where(active_base, BillingRecord.denial_reason_code.isnot(None))
        .group_by(BillingRecord.denial_reason_code)
        .order_by(func.count().desc())
        .limit(10)
    )
    reason_result = await db.execute(reason_q)
    by_reason = [{"reason": r.reason, "count": r.count} for r in reason_result]

    # Appealed count (still active — not yet resolved)
    appealed = (await db.execute(
        select(func.count()).where(BillingRecord.denial_status == "APPEALED")
    )).scalar() or 0

    # Written off / resolved count (for reference, not in active total)
    written_off = (await db.execute(
        select(func.count()).where(is_written_off())
    )).scalar() or 0

    return {
        "total_denied": total_denied,
        "appealed": appealed,
        "written_off": written_off,
        "pending": total_denied - appealed,
        "by_status": by_status,
        "by_carrier": by_carrier,
        "by_reason": by_reason,
    }


async def appeal_denial(
    db: AsyncSession,
    billing_id: int,
    notes: str | None = None,
    appeal_date: str | None = None,
) -> dict:
    """Mark a denied claim as APPEALED."""
    stmt = select(BillingRecord).where(BillingRecord.id == billing_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        return {"error": "Claim not found", "id": billing_id}

    record.denial_status = "APPEALED"
    if notes:
        extra = record.extra_data or {}
        extra["appeal_notes"] = notes
        extra["appeal_date"] = appeal_date or str(date.today())
        record.extra_data = extra

    await db.commit()
    return {"status": "APPEALED", "id": billing_id}


async def resolve_denial(
    db: AsyncSession,
    billing_id: int,
    resolution: str,
    amount: float | None = None,
) -> dict:
    """Resolve a denial as RESOLVED (paid) or WRITTEN_OFF."""
    stmt = select(BillingRecord).where(BillingRecord.id == billing_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        return {"error": "Claim not found", "id": billing_id}

    resolution = resolution.upper()
    if resolution not in ("RESOLVED", "WRITTEN_OFF"):
        return {"error": "Resolution must be RESOLVED or WRITTEN_OFF"}

    record.denial_status = resolution
    if amount is not None and resolution == "RESOLVED":
        record.total_payment = Decimal(str(amount))

    extra = record.extra_data or {}
    extra["resolved_at"] = str(datetime.utcnow())
    extra["resolution_type"] = resolution
    if amount is not None:
        extra["resolution_amount"] = amount
    record.extra_data = extra

    await db.commit()
    return {"status": resolution, "id": billing_id, "amount": amount}


async def bulk_appeal(
    db: AsyncSession,
    billing_ids: list[int],
    notes: str | None = None,
) -> dict:
    """Bulk mark claims as APPEALED."""
    stmt = (
        update(BillingRecord)
        .where(BillingRecord.id.in_(billing_ids))
        .values(denial_status="APPEALED")
    )
    result = await db.execute(stmt)
    await db.commit()
    return {"status": "APPEALED", "updated": result.rowcount, "ids": billing_ids}


async def get_denial_full_detail(
    db: AsyncSession,
    billing_id: int,
) -> dict:
    """
    Get complete denial detail for a single claim — all ERA context,
    CARC code explanation, CAS group meaning, suggested fix, and
    related claims from the same patient.
    """
    stmt = select(BillingRecord).where(BillingRecord.id == billing_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        return {"error": "Claim not found", "id": billing_id}

    # Get ERA claim line detail
    era_info = None
    era_detail = None
    if record.era_claim_id:
        era_q = select(ERAClaimLine).where(
            ERAClaimLine.claim_id == record.era_claim_id
        )
        era_result = await db.execute(era_q)
        ecl = era_result.scalar_one_or_none()
        if ecl:
            era_info = {
                "billed_amount": float(ecl.billed_amount or 0),
                "cas_group_code": ecl.cas_group_code,
                "cas_reason_code": ecl.cas_reason_code,
                "cas_adjustment_amount": float(ecl.cas_adjustment_amount or 0) if ecl.cas_adjustment_amount else None,
            }
            # Get parent payment for payer context
            payment = None
            if ecl.era_payment_id:
                pay_q = select(ERAPayment).where(ERAPayment.id == ecl.era_payment_id)
                pay_result = await db.execute(pay_q)
                payment = pay_result.scalar_one_or_none()

            era_detail = {
                "claim_id": ecl.claim_id,
                "claim_status": ecl.claim_status,
                "billed_amount": float(ecl.billed_amount or 0),
                "paid_amount": float(ecl.paid_amount or 0),
                "patient_name_835": ecl.patient_name_835,
                "service_date_835": str(ecl.service_date_835) if ecl.service_date_835 else None,
                "cpt_code": ecl.cpt_code,
                "cas_group_code": ecl.cas_group_code,
                "cas_reason_code": ecl.cas_reason_code,
                "cas_adjustment_amount": float(ecl.cas_adjustment_amount or 0) if ecl.cas_adjustment_amount else None,
                "match_confidence": ecl.match_confidence,
                "payer_name": payment.payer_name if payment else None,
                "payment_date": str(payment.payment_date) if payment and payment.payment_date else None,
                "check_number": payment.check_eft_number if payment else None,
            }

    # Build the main denial serialization
    denial = _serialize_denial(record, era_info)

    # Get full action detail
    carc = era_info.get("cas_reason_code") if era_info else record.denial_reason_code
    cas_group = era_info.get("cas_group_code") if era_info else None
    action_detail = get_denial_detail(
        carc_code=carc,
        cas_group=cas_group,
        billed_amount=denial["billed_amount"],
        paid_amount=denial["total_payment"],
        adjustment_amount=float(era_info.get("cas_adjustment_amount") or 0) if era_info else 0,
        days_old=denial["days_old"] or 0,
        carrier=record.insurance_carrier,
    )

    # Find related claims for same patient
    related = []
    if record.patient_id:
        rel_q = (
            select(BillingRecord)
            .where(
                BillingRecord.patient_id == record.patient_id,
                BillingRecord.id != billing_id,
            )
            .order_by(BillingRecord.service_date.desc())
            .limit(10)
        )
        rel_result = await db.execute(rel_q)
        for r in rel_result.scalars().all():
            related.append({
                "id": r.id,
                "service_date": str(r.service_date) if r.service_date else None,
                "modality": r.modality,
                "total_payment": float(r.total_payment or 0),
                "denial_status": r.denial_status,
            })

    # Appeal history from extra_data
    appeal_history = []
    extra = record.extra_data or {}
    if extra.get("appeal_date"):
        appeal_history.append({
            "action": "APPEALED",
            "date": extra["appeal_date"],
            "notes": extra.get("appeal_notes"),
        })
    if extra.get("resolved_at"):
        appeal_history.append({
            "action": extra.get("resolution_type", "RESOLVED"),
            "date": extra["resolved_at"],
            "amount": extra.get("resolution_amount"),
        })

    return {
        "denial": denial,
        "era_detail": era_detail,
        "action_detail": action_detail,
        "related_claims": related,
        "appeal_history": appeal_history,
    }


async def export_denials(
    db: AsyncSession,
    status: str | None = None,
    carrier: str | None = None,
) -> list[dict]:
    """Export all denials as flat rows for CSV/XLSX export."""
    conditions = [
        BillingRecord.total_payment == 0,
        BillingRecord.denial_status.isnot(None),
    ]
    query = select(BillingRecord).where(or_(*conditions))
    if status:
        query = query.where(BillingRecord.denial_status == status.upper())
    if carrier:
        query = query.where(BillingRecord.insurance_carrier.ilike(f"%{carrier}%"))
    query = query.order_by(BillingRecord.service_date.desc())

    result = await db.execute(query)
    rows = result.scalars().all()

    # Batch fetch ERA info
    era_claim_ids = [r.era_claim_id for r in rows if r.era_claim_id]
    era_map = {}
    if era_claim_ids:
        era_q = select(ERAClaimLine).where(ERAClaimLine.claim_id.in_(era_claim_ids))
        era_result = await db.execute(era_q)
        for ecl in era_result.scalars().all():
            era_map[ecl.claim_id] = {
                "billed_amount": float(ecl.billed_amount or 0),
                "cas_group_code": ecl.cas_group_code,
                "cas_reason_code": ecl.cas_reason_code,
                "cas_adjustment_amount": float(ecl.cas_adjustment_amount or 0) if ecl.cas_adjustment_amount else None,
            }

    return [_serialize_denial(r, era_map.get(r.era_claim_id)) for r in rows]
