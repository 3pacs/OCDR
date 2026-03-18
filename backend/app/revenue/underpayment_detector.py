"""
Underpayment Detector (F-05).

Compares total_payment vs fee_schedule.expected_rate for each paid claim.
Flags if payment < underpayment_threshold (default 80%).
Implements BR-03 (gado premium) and BR-02 (PSMA rate).
"""

import logging

from sqlalchemy import select, func, case, and_, literal
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.payer import FeeSchedule
from backend.app.revenue.writeoff_filter import not_written_off

logger = logging.getLogger(__name__)

GADO_PREMIUM = 200.00  # BR-03


async def get_underpayments(
    session: AsyncSession,
    carrier: str | None = None,
    modality: str | None = None,
    threshold_override: float | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """
    Find underpaid claims by comparing to fee schedule.

    Returns paginated list of underpaid claims with variance details.
    """
    # Build base query: join billing_records with fee_schedule
    # First try payer-specific rate, then fall back to DEFAULT
    fee_sub = (
        select(
            FeeSchedule.modality,
            FeeSchedule.payer_code,
            FeeSchedule.expected_rate,
            FeeSchedule.underpayment_threshold,
        )
        .subquery()
    )

    # Get all paid claims (exclude written-off / resolved / carrier X)
    query = select(BillingRecord).where(
        BillingRecord.total_payment > 0,
        not_written_off(),
    )

    if carrier:
        query = query.where(BillingRecord.insurance_carrier == carrier)
    if modality:
        query = query.where(BillingRecord.modality == modality)

    query = query.order_by(BillingRecord.service_date.desc())

    # Get total count
    count_q = select(func.count()).select_from(query.subquery())
    total_result = await session.execute(count_q)
    total_paid = total_result.scalar()

    # Get paginated results
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await session.execute(query)
    records = result.scalars().all()

    # Load fee schedule into memory for lookups
    fee_result = await session.execute(select(FeeSchedule))
    fees = fee_result.scalars().all()

    fee_lookup: dict[tuple[str, str], tuple[float, float]] = {}
    default_lookup: dict[str, tuple[float, float]] = {}
    for f in fees:
        if f.payer_code == "DEFAULT":
            default_lookup[f.modality] = (float(f.expected_rate), float(f.underpayment_threshold))
        else:
            fee_lookup[(f.payer_code, f.modality)] = (float(f.expected_rate), float(f.underpayment_threshold))

    underpaid = []
    for rec in records:
        # Determine expected rate
        key = (rec.insurance_carrier, rec.modality)
        if key in fee_lookup:
            expected, thresh = fee_lookup[key]
        elif rec.modality in default_lookup:
            expected, thresh = default_lookup[rec.modality]
        else:
            continue  # No fee schedule for this modality

        # BR-02: PSMA PET uses higher rate
        if rec.is_psma and "PET_PSMA" in default_lookup:
            expected, thresh = default_lookup["PET_PSMA"]

        # BR-03: Gado premium
        if rec.gado_used and rec.modality in ("HMRI", "OPEN"):
            expected += GADO_PREMIUM

        if threshold_override is not None:
            thresh = threshold_override

        total = float(rec.total_payment)
        if total < expected * thresh:
            variance = total - expected
            underpaid.append({
                "id": rec.id,
                "patient_name": rec.patient_name,
                "service_date": rec.service_date.isoformat(),
                "modality": rec.modality,
                "insurance_carrier": rec.insurance_carrier,
                "total_payment": total,
                "expected_rate": expected,
                "variance": round(variance, 2),
                "variance_pct": round((total / expected) * 100, 1) if expected > 0 else 0,
                "gado_used": rec.gado_used,
                "is_psma": rec.is_psma,
            })

    return {
        "underpaid_claims": underpaid,
        "total_paid_claims": total_paid,
        "page": page,
        "per_page": per_page,
    }


async def get_underpayment_summary(session: AsyncSession) -> dict:
    """
    Summary statistics for underpayments across all paid claims.
    """
    # Get all paid claims (exclude written-off / resolved)
    result = await session.execute(
        select(BillingRecord).where(
            BillingRecord.total_payment > 0,
            or_(
                BillingRecord.denial_status.is_(None),
                ~BillingRecord.denial_status.in_(TERMINAL_STATUSES),
            ),
        )
    )
    records = result.scalars().all()

    # Load fee schedule
    fee_result = await session.execute(select(FeeSchedule))
    fees = fee_result.scalars().all()

    fee_lookup: dict[tuple[str, str], tuple[float, float]] = {}
    default_lookup: dict[str, tuple[float, float]] = {}
    for f in fees:
        if f.payer_code == "DEFAULT":
            default_lookup[f.modality] = (float(f.expected_rate), float(f.underpayment_threshold))
        else:
            fee_lookup[(f.payer_code, f.modality)] = (float(f.expected_rate), float(f.underpayment_threshold))

    total_flagged = 0
    total_variance = 0.0
    by_carrier: dict[str, dict] = {}
    by_modality: dict[str, dict] = {}

    for rec in records:
        key = (rec.insurance_carrier, rec.modality)
        if key in fee_lookup:
            expected, thresh = fee_lookup[key]
        elif rec.modality in default_lookup:
            expected, thresh = default_lookup[rec.modality]
        else:
            continue

        if rec.is_psma and "PET_PSMA" in default_lookup:
            expected, thresh = default_lookup["PET_PSMA"]

        if rec.gado_used and rec.modality in ("HMRI", "OPEN"):
            expected += GADO_PREMIUM

        total = float(rec.total_payment)
        if total < expected * thresh:
            variance = total - expected
            total_flagged += 1
            total_variance += variance

            # By carrier
            c = rec.insurance_carrier
            if c not in by_carrier:
                by_carrier[c] = {"count": 0, "variance": 0.0}
            by_carrier[c]["count"] += 1
            by_carrier[c]["variance"] += variance

            # By modality
            m = rec.modality
            if m not in by_modality:
                by_modality[m] = {"count": 0, "variance": 0.0}
            by_modality[m]["count"] += 1
            by_modality[m]["variance"] += variance

    # Sort and round
    by_carrier_list = [
        {"carrier": k, "count": v["count"], "variance": round(v["variance"], 2)}
        for k, v in sorted(by_carrier.items(), key=lambda x: x[1]["variance"])
    ]
    by_modality_list = [
        {"modality": k, "count": v["count"], "variance": round(v["variance"], 2)}
        for k, v in sorted(by_modality.items(), key=lambda x: x[1]["variance"])
    ]

    return {
        "total_flagged": total_flagged,
        "total_paid_claims": len(records),
        "flagged_pct": round(total_flagged / len(records) * 100, 1) if records else 0,
        "total_variance": round(total_variance, 2),
        "by_carrier": by_carrier_list,
        "by_modality": by_modality_list,
    }
