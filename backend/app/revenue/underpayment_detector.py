"""
Underpayment Detector (F-05).

Compares total_payment vs fee_schedule.expected_rate for each paid claim.
Flags if payment < underpayment_threshold (default 80%).

Rate lookup priority:
  1. (payer, modality, cpt_code) — CPT-specific payer rate
  2. (payer, modality, NULL)     — modality-level payer rate
  3. (DEFAULT, modality, cpt_code) — CPT-specific default rate
  4. (DEFAULT, modality, NULL)   — modality-level default rate

Billing cycle exclusion:
  Claims within the last 30 days are in the "active billing cycle" —
  they haven't had time to be paid yet and should NOT be flagged as
  underpaid. This prevents false positives on recent scans.

Implements BR-03 (gado premium) and BR-02 (PSMA rate).
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAClaimLine
from backend.app.models.payer import FeeSchedule
from backend.app.revenue.writeoff_filter import not_written_off

logger = logging.getLogger(__name__)

GADO_PREMIUM = 200.00  # BR-03
BILLING_CYCLE_DAYS = 30  # Claims within this window are still in active billing


def _build_fee_lookups(fees: list) -> tuple[dict, dict, dict, dict]:
    """Build tiered fee schedule lookup dicts.

    Returns:
        payer_cpt_lookup: {(carrier, modality, cpt): (rate, thresh)}
        payer_mod_lookup: {(carrier, modality): (rate, thresh)}
        default_cpt_lookup: {(modality, cpt): (rate, thresh)}
        default_mod_lookup: {modality: (rate, thresh)}
    """
    payer_cpt: dict[tuple[str, str, str], tuple[float, float]] = {}
    payer_mod: dict[tuple[str, str], tuple[float, float]] = {}
    default_cpt: dict[tuple[str, str], tuple[float, float]] = {}
    default_mod: dict[str, tuple[float, float]] = {}

    for f in fees:
        rate = float(f.expected_rate)
        thresh = float(f.underpayment_threshold)
        cpt = f.cpt_code

        if f.payer_code == "DEFAULT":
            if cpt:
                default_cpt[(f.modality, cpt)] = (rate, thresh)
            else:
                default_mod[f.modality] = (rate, thresh)
        else:
            if cpt:
                payer_cpt[(f.payer_code, f.modality, cpt)] = (rate, thresh)
            else:
                payer_mod[(f.payer_code, f.modality)] = (rate, thresh)

    return payer_cpt, payer_mod, default_cpt, default_mod


def _lookup_expected_rate(
    carrier: str,
    modality: str,
    cpt_code: str | None,
    is_psma: bool,
    gado_used: bool,
    payer_cpt: dict,
    payer_mod: dict,
    default_cpt: dict,
    default_mod: dict,
    threshold_override: float | None = None,
) -> tuple[float, float] | None:
    """Look up expected rate using tiered priority.

    Returns (expected_rate, threshold) or None if no schedule found.
    """
    expected = None
    thresh = None

    # Priority 1: payer + modality + CPT
    if cpt_code:
        key = (carrier, modality, cpt_code)
        if key in payer_cpt:
            expected, thresh = payer_cpt[key]

    # Priority 2: payer + modality (no CPT)
    if expected is None:
        key = (carrier, modality)
        if key in payer_mod:
            expected, thresh = payer_mod[key]

    # Priority 3: DEFAULT + modality + CPT
    if expected is None and cpt_code:
        key = (modality, cpt_code)
        if key in default_cpt:
            expected, thresh = default_cpt[key]

    # Priority 4: DEFAULT + modality
    if expected is None:
        if modality in default_mod:
            expected, thresh = default_mod[modality]

    if expected is None:
        return None

    # BR-02: PSMA PET override
    if is_psma and "PET_PSMA" in default_mod:
        expected, thresh = default_mod["PET_PSMA"]

    # BR-03: Gado premium
    if gado_used and modality in ("HMRI", "OPEN"):
        expected += GADO_PREMIUM

    if threshold_override is not None:
        thresh = threshold_override

    return expected, thresh


async def _get_cpt_for_billing(session: AsyncSession, billing_ids: list[int]) -> dict[int, str]:
    """Get CPT codes from matched ERA claims for billing records."""
    if not billing_ids:
        return {}
    result = await session.execute(
        select(ERAClaimLine.matched_billing_id, ERAClaimLine.cpt_code).where(
            ERAClaimLine.matched_billing_id.in_(billing_ids),
            ERAClaimLine.cpt_code.isnot(None),
        )
    )
    cpt_map: dict[int, str] = {}
    for billing_id, cpt in result.all():
        if billing_id not in cpt_map:  # First (primary) claim wins
            cpt_map[billing_id] = cpt
    return cpt_map


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

    Excludes claims from the last 30 days (active billing cycle).
    Uses CPT-granular rates when available, falls back to modality-level.
    """
    cutoff_date = date.today() - timedelta(days=BILLING_CYCLE_DAYS)

    # Get paid claims outside active billing cycle
    query = select(BillingRecord).where(
        BillingRecord.total_payment > 0,
        BillingRecord.service_date <= cutoff_date,
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

    # Load fee schedule
    fee_result = await session.execute(select(FeeSchedule))
    fees = fee_result.scalars().all()
    payer_cpt, payer_mod, default_cpt, default_mod = _build_fee_lookups(fees)

    # Get CPT codes from matched ERA claims
    billing_ids = [rec.id for rec in records]
    cpt_map = await _get_cpt_for_billing(session, billing_ids)

    underpaid = []
    for rec in records:
        cpt_code = cpt_map.get(rec.id)

        rate_result = _lookup_expected_rate(
            rec.insurance_carrier, rec.modality, cpt_code,
            rec.is_psma, rec.gado_used,
            payer_cpt, payer_mod, default_cpt, default_mod,
            threshold_override,
        )
        if rate_result is None:
            continue

        expected, thresh = rate_result
        total = float(rec.total_payment)
        if total < expected * thresh:
            variance = total - expected
            underpaid.append({
                "id": rec.id,
                "patient_name": rec.patient_name,
                "service_date": rec.service_date.isoformat(),
                "modality": rec.modality,
                "cpt_code": cpt_code,
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
        "billing_cycle_excluded_days": BILLING_CYCLE_DAYS,
        "cutoff_date": cutoff_date.isoformat(),
        "page": page,
        "per_page": per_page,
    }


async def get_underpayment_summary(session: AsyncSession) -> dict:
    """
    Summary statistics for underpayments across all paid claims.

    Excludes claims from the last 30 days (active billing cycle).
    """
    cutoff_date = date.today() - timedelta(days=BILLING_CYCLE_DAYS)

    result = await session.execute(
        select(BillingRecord).where(
            BillingRecord.total_payment > 0,
            BillingRecord.service_date <= cutoff_date,
            not_written_off(),
        )
    )
    records = result.scalars().all()

    # Load fee schedule
    fee_result = await session.execute(select(FeeSchedule))
    fees = fee_result.scalars().all()
    payer_cpt, payer_mod, default_cpt, default_mod = _build_fee_lookups(fees)

    # Get CPT codes for all records
    billing_ids = [rec.id for rec in records]
    cpt_map = await _get_cpt_for_billing(session, billing_ids)

    total_flagged = 0
    total_variance = 0.0
    by_carrier: dict[str, dict] = {}
    by_modality: dict[str, dict] = {}

    for rec in records:
        cpt_code = cpt_map.get(rec.id)
        rate_result = _lookup_expected_rate(
            rec.insurance_carrier, rec.modality, cpt_code,
            rec.is_psma, rec.gado_used,
            payer_cpt, payer_mod, default_cpt, default_mod,
        )
        if rate_result is None:
            continue

        expected, thresh = rate_result
        total = float(rec.total_payment)
        if total < expected * thresh:
            variance = total - expected
            total_flagged += 1
            total_variance += variance

            c = rec.insurance_carrier
            if c not in by_carrier:
                by_carrier[c] = {"count": 0, "variance": 0.0}
            by_carrier[c]["count"] += 1
            by_carrier[c]["variance"] += variance

            m = rec.modality
            if m not in by_modality:
                by_modality[m] = {"count": 0, "variance": 0.0}
            by_modality[m]["count"] += 1
            by_modality[m]["variance"] += variance

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
        "billing_cycle_excluded_days": BILLING_CYCLE_DAYS,
        "cutoff_date": cutoff_date.isoformat(),
        "by_carrier": by_carrier_list,
        "by_modality": by_modality_list,
    }
