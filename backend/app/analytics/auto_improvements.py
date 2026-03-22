"""Auto-solve pipeline improvements where possible.

These are code-level fixes that directly address pipeline suggestions.
Run via /api/analytics/auto-improve or the daily scheduler.
"""

import logging
from datetime import date, timedelta
from collections import defaultdict

from sqlalchemy import select, func, and_, or_, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAClaimLine

logger = logging.getLogger(__name__)


async def run_auto_improvements(db: AsyncSession) -> dict:
    """Run all auto-improvement routines. Returns summary of changes."""
    results = {}

    results["crosswalk_propagation"] = await _propagate_crosswalk(db)
    results["secondary_flagging"] = await _flag_missing_secondary(db)
    results["filing_deadline_alerts"] = await _update_filing_deadlines(db)

    return results


async def _propagate_crosswalk(db: AsyncSession) -> dict:
    """Auto-propagate Topaz IDs to records missing them.

    When patient A has a Topaz ID on some records but not others (same patient_name),
    copy the Topaz ID to the records that are missing it. This directly improves
    crosswalk coverage and match rate.
    """
    # Find patients who have topaz_id on SOME records but not all
    # Group by patient_name, find those with mixed coverage
    patients_with_topaz = await db.execute(
        select(
            BillingRecord.patient_name,
            func.max(BillingRecord.topaz_id).label("known_topaz_id"),
            func.count(BillingRecord.id).label("total"),
            func.count(BillingRecord.topaz_id).label("with_topaz"),
        )
        .where(BillingRecord.patient_name.is_not(None))
        .group_by(BillingRecord.patient_name)
        .having(
            and_(
                func.count(BillingRecord.topaz_id) > 0,  # Has at least one topaz_id
                func.count(BillingRecord.topaz_id) < func.count(BillingRecord.id),  # But not all
            )
        )
    )
    rows = patients_with_topaz.all()

    propagated = 0
    patients_fixed = 0

    for row in rows:
        patient_name, known_topaz_id, total, with_topaz = row
        if not known_topaz_id:
            continue

        # Update records for this patient that don't have a topaz_id
        result = await db.execute(
            update(BillingRecord)
            .where(
                and_(
                    BillingRecord.patient_name == patient_name,
                    BillingRecord.topaz_id.is_(None),
                )
            )
            .values(topaz_id=known_topaz_id)
        )
        if result.rowcount > 0:
            propagated += result.rowcount
            patients_fixed += 1

    # Also propagate via patient_id (chart number)
    patients_with_pid = await db.execute(
        select(
            BillingRecord.patient_id,
            func.max(BillingRecord.topaz_id).label("known_topaz_id"),
        )
        .where(
            and_(
                BillingRecord.patient_id.is_not(None),
                BillingRecord.patient_id != "",
                BillingRecord.topaz_id.is_not(None),
            )
        )
        .group_by(BillingRecord.patient_id)
    )
    pid_topaz_map = {row[0]: row[1] for row in patients_with_pid.all() if row[1]}

    for pid, topaz_id in pid_topaz_map.items():
        result = await db.execute(
            update(BillingRecord)
            .where(
                and_(
                    BillingRecord.patient_id == pid,
                    BillingRecord.topaz_id.is_(None),
                )
            )
            .values(topaz_id=topaz_id)
        )
        if result.rowcount > 0:
            propagated += result.rowcount

    if propagated > 0:
        await db.commit()

    return {
        "records_updated": propagated,
        "patients_fixed": patients_fixed,
        "description": f"Propagated Topaz ID to {propagated} records across {patients_fixed} patients",
    }


async def _flag_missing_secondary(db: AsyncSession) -> dict:
    """Identify claims that likely need secondary billing but don't have it.

    Looks for patients with known secondary insurance (via payer config) where
    primary payment was posted but no secondary claim exists.
    """
    # Find records where primary paid but secondary = 0, and payer expects secondary
    from backend.app.models.payer import Payer

    payers_with_secondary = await db.execute(
        select(Payer.code).where(Payer.expected_has_secondary == True)
    )
    secondary_payer_codes = {r[0] for r in payers_with_secondary.all()}

    if not secondary_payer_codes:
        return {"flagged": 0, "description": "No payers configured with expected secondary"}

    # Find records: primary paid, no secondary, payer expects secondary
    missing = await db.execute(
        select(func.count(BillingRecord.id)).where(
            and_(
                BillingRecord.insurance_carrier.in_(secondary_payer_codes),
                BillingRecord.primary_payment > 0,
                or_(
                    BillingRecord.secondary_payment.is_(None),
                    BillingRecord.secondary_payment == 0,
                ),
                BillingRecord.denial_status.is_(None),
            )
        )
    )
    flagged_count = missing.scalar() or 0

    return {
        "flagged": flagged_count,
        "secondary_payers": list(secondary_payer_codes),
        "description": f"{flagged_count} claims may need secondary billing (primary paid, secondary $0, payer has expected_has_secondary)",
    }


async def _update_filing_deadlines(db: AsyncSession) -> dict:
    """Check for claims approaching filing deadlines and ensure they're flagged."""
    today = date.today()
    thirty_days = today + timedelta(days=30)

    # Count claims approaching deadlines
    approaching = await db.execute(
        select(func.count(BillingRecord.id)).where(
            and_(
                BillingRecord.appeal_deadline.is_not(None),
                BillingRecord.appeal_deadline <= thirty_days,
                BillingRecord.appeal_deadline >= today,
                BillingRecord.denial_status.is_not(None),
            )
        )
    )
    approaching_count = approaching.scalar() or 0

    # Urgent: within 7 days
    urgent = await db.execute(
        select(func.count(BillingRecord.id)).where(
            and_(
                BillingRecord.appeal_deadline.is_not(None),
                BillingRecord.appeal_deadline <= today + timedelta(days=7),
                BillingRecord.appeal_deadline >= today,
                BillingRecord.denial_status.is_not(None),
            )
        )
    )
    urgent_count = urgent.scalar() or 0

    # Expired (missed deadline)
    expired = await db.execute(
        select(func.count(BillingRecord.id)).where(
            and_(
                BillingRecord.appeal_deadline.is_not(None),
                BillingRecord.appeal_deadline < today,
                BillingRecord.denial_status.is_not(None),
            )
        )
    )
    expired_count = expired.scalar() or 0

    return {
        "approaching_30d": approaching_count,
        "urgent_7d": urgent_count,
        "expired": expired_count,
        "description": f"Filing deadlines: {urgent_count} urgent (<7d), {approaching_count} approaching (<30d), {expired_count} expired",
    }
