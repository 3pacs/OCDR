"""F-07: Secondary Insurance Follow-Up Queue.

Identifies claims where primary_payment > 0 AND secondary_payment = 0
AND payers.expected_has_secondary = TRUE. Queue for billing follow-up.
Known finding: 1,919 claims, est. $643K missing.
"""

from datetime import date

from sqlalchemy import select, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.payer import Payer
from backend.app.revenue.writeoff_filter import not_written_off


# Carriers known to expect secondary insurance
EXPECTED_SECONDARY_CARRIERS = {"M/M", "CALOPTIMA"}


def _serialize_followup(row: BillingRecord, payer_info: dict | None = None) -> dict:
    primary = float(row.primary_payment or 0)
    # Estimate missing secondary as ~33% of primary (industry avg for Medi-Cal crossover)
    est_secondary = round(primary * 0.335, 2) if primary > 0 else 0

    return {
        "id": row.id,
        "patient_name": row.patient_name,
        "service_date": str(row.service_date) if row.service_date else None,
        "insurance_carrier": row.insurance_carrier,
        "modality": row.modality,
        "scan_type": row.scan_type,
        "referring_doctor": row.referring_doctor,
        "primary_payment": primary,
        "secondary_payment": float(row.secondary_payment or 0),
        "total_payment": float(row.total_payment or 0),
        "estimated_secondary": est_secondary,
        "followup_status": (row.extra_data or {}).get("secondary_followup_status", "PENDING"),
        "days_since_service": (date.today() - row.service_date).days if row.service_date else None,
        "priority": "HIGH" if row.insurance_carrier in ("M/M",) else "MEDIUM",
        "patient_id": row.patient_id,
        "appeal_deadline": str(row.appeal_deadline) if row.appeal_deadline else None,
    }


async def _get_secondary_carriers(db: AsyncSession) -> set[str]:
    """Get payer codes where expected_has_secondary=TRUE."""
    q = select(Payer.code).where(Payer.expected_has_secondary == True)
    result = await db.execute(q)
    db_carriers = {r[0] for r in result}
    return db_carriers | EXPECTED_SECONDARY_CARRIERS


async def get_secondary_followup(
    db: AsyncSession,
    carrier: str | None = None,
    status: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """List claims missing expected secondary payment."""
    expected_carriers = await _get_secondary_carriers(db)

    query = select(BillingRecord).where(
        BillingRecord.primary_payment > 0,
        BillingRecord.secondary_payment == 0,
        BillingRecord.insurance_carrier.in_(expected_carriers),
        not_written_off(),
    )

    if carrier:
        query = query.where(BillingRecord.insurance_carrier.ilike(f"%{carrier}%"))

    # Filter by followup status in extra_data is complex; filter in Python for now
    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar() or 0

    query = query.order_by(
        BillingRecord.primary_payment.desc(),
        BillingRecord.service_date.desc(),
    )
    query = query.offset((page - 1) * per_page).limit(per_page)

    result = await db.execute(query)
    rows = result.scalars().all()

    claims = [_serialize_followup(r) for r in rows]

    # Filter by status if requested
    if status:
        claims = [c for c in claims if c["followup_status"] == status.upper()]

    return {"total": total, "page": page, "per_page": per_page, "claims": claims}


async def get_secondary_summary(db: AsyncSession) -> dict:
    """Summary statistics for missing secondary payments."""
    expected_carriers = await _get_secondary_carriers(db)

    base_where = and_(
        BillingRecord.primary_payment > 0,
        BillingRecord.secondary_payment == 0,
        BillingRecord.insurance_carrier.in_(expected_carriers),
        not_written_off(),
    )

    # Total missing
    total_q = select(func.count(), func.sum(BillingRecord.primary_payment)).where(base_where)
    result = await db.execute(total_q)
    row = result.one()
    total_claims = row[0] or 0
    total_primary = float(row[1] or 0)
    est_missing = round(total_primary * 0.335, 2)

    # By carrier
    carrier_q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            func.count().label("count"),
            func.sum(BillingRecord.primary_payment).label("primary_total"),
        )
        .where(base_where)
        .group_by(BillingRecord.insurance_carrier)
        .order_by(func.count().desc())
    )
    carrier_result = await db.execute(carrier_q)
    by_carrier = [
        {
            "carrier": r.carrier,
            "count": r.count,
            "primary_total": float(r.primary_total or 0),
            "estimated_secondary": round(float(r.primary_total or 0) * 0.335, 2),
        }
        for r in carrier_result
    ]

    # By modality
    mod_q = (
        select(
            BillingRecord.modality.label("modality"),
            func.count().label("count"),
            func.sum(BillingRecord.primary_payment).label("primary_total"),
        )
        .where(base_where)
        .group_by(BillingRecord.modality)
        .order_by(func.sum(BillingRecord.primary_payment).desc())
    )
    mod_result = await db.execute(mod_q)
    by_modality = [
        {
            "modality": r.modality,
            "count": r.count,
            "primary_total": float(r.primary_total or 0),
        }
        for r in mod_result
    ]

    return {
        "total_claims": total_claims,
        "total_primary_paid": total_primary,
        "estimated_missing_secondary": est_missing,
        "by_carrier": by_carrier,
        "by_modality": by_modality,
    }


async def mark_followup(
    db: AsyncSession,
    billing_id: int,
    status: str,
    notes: str | None = None,
) -> dict:
    """Mark a claim's secondary follow-up status.

    Statuses: PENDING, BILLED, RECEIVED, WRITTEN_OFF
    """
    valid = {"PENDING", "BILLED", "RECEIVED", "WRITTEN_OFF"}
    status = status.upper()
    if status not in valid:
        return {"error": f"Status must be one of: {', '.join(sorted(valid))}"}

    stmt = select(BillingRecord).where(BillingRecord.id == billing_id)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    if not record:
        return {"error": "Claim not found", "id": billing_id}

    extra = record.extra_data or {}
    extra["secondary_followup_status"] = status
    if notes:
        extra["secondary_followup_notes"] = notes
    extra["secondary_followup_updated"] = str(date.today())
    record.extra_data = extra

    if status == "RECEIVED" and record.secondary_payment == 0:
        # Placeholder - actual amount would be entered separately
        pass

    await db.commit()
    return {"status": status, "id": billing_id}


async def bulk_mark_followup(
    db: AsyncSession,
    billing_ids: list[int],
    status: str,
) -> dict:
    """Bulk mark claims' secondary follow-up status."""
    valid = {"PENDING", "BILLED", "RECEIVED", "WRITTEN_OFF"}
    status = status.upper()
    if status not in valid:
        return {"error": f"Status must be one of: {', '.join(sorted(valid))}"}

    # Need to update extra_data for each record individually since it's JSON
    stmt = select(BillingRecord).where(BillingRecord.id.in_(billing_ids))
    result = await db.execute(stmt)
    records = result.scalars().all()

    for record in records:
        extra = record.extra_data or {}
        extra["secondary_followup_status"] = status
        extra["secondary_followup_updated"] = str(date.today())
        record.extra_data = extra

    await db.commit()
    return {"status": status, "updated": len(records), "ids": billing_ids}
