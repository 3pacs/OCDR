"""Auto-solve pipeline improvements where possible.

These are code-level fixes that directly address pipeline suggestions.
Run via /api/analytics/auto-improve or the daily scheduler.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import func, and_, or_, update

from app.models import db, BillingRecord, EraClaimLine

logger = logging.getLogger(__name__)


def run_auto_improvements() -> dict:
    """Run all auto-improvement routines. Returns summary of changes."""
    results = {}
    results["crosswalk_propagation"] = _propagate_crosswalk()
    results["secondary_flagging"] = _flag_missing_secondary()
    results["filing_deadline_alerts"] = _update_filing_deadlines()
    return results


def _propagate_crosswalk() -> dict:
    """Auto-propagate Topaz IDs to records missing them."""
    rows = db.session.query(
        BillingRecord.patient_name,
        func.max(BillingRecord.topaz_patient_id).label("known_topaz_id"),
        func.count(BillingRecord.id).label("total"),
        func.count(BillingRecord.topaz_patient_id).label("with_topaz"),
    ).filter(
        BillingRecord.patient_name.is_not(None)
    ).group_by(BillingRecord.patient_name).having(
        and_(
            func.count(BillingRecord.topaz_patient_id) > 0,
            func.count(BillingRecord.topaz_patient_id) < func.count(BillingRecord.id),
        )
    ).all()

    propagated = 0
    patients_fixed = 0

    for patient_name, known_topaz_id, total, with_topaz in rows:
        if not known_topaz_id:
            continue
        result = db.session.execute(
            update(BillingRecord).where(
                and_(
                    BillingRecord.patient_name == patient_name,
                    BillingRecord.topaz_patient_id.is_(None),
                )
            ).values(topaz_patient_id=known_topaz_id)
        )
        if result.rowcount > 0:
            propagated += result.rowcount
            patients_fixed += 1

    # Also propagate via patient_id
    pid_rows = db.session.query(
        BillingRecord.patient_id,
        func.max(BillingRecord.topaz_patient_id).label("known_topaz_id"),
    ).filter(
        and_(
            BillingRecord.patient_id.is_not(None),
            BillingRecord.patient_id != "",
            BillingRecord.topaz_patient_id.is_not(None),
        )
    ).group_by(BillingRecord.patient_id).all()

    pid_topaz_map = {row[0]: row[1] for row in pid_rows if row[1]}

    for pid, topaz_id in pid_topaz_map.items():
        result = db.session.execute(
            update(BillingRecord).where(
                and_(
                    BillingRecord.patient_id == pid,
                    BillingRecord.topaz_patient_id.is_(None),
                )
            ).values(topaz_patient_id=topaz_id)
        )
        if result.rowcount > 0:
            propagated += result.rowcount

    if propagated > 0:
        db.session.commit()

    return {
        "records_updated": propagated,
        "patients_fixed": patients_fixed,
        "description": f"Propagated Topaz ID to {propagated} records across {patients_fixed} patients",
    }


def _flag_missing_secondary() -> dict:
    """Identify claims that likely need secondary billing."""
    from app.models import Payer

    secondary_payer_codes = {
        r[0] for r in db.session.query(Payer.code).filter(
            Payer.expected_has_secondary == True
        ).all()
    }

    if not secondary_payer_codes:
        return {"flagged": 0, "description": "No payers configured with expected secondary"}

    flagged_count = db.session.query(func.count(BillingRecord.id)).filter(
        and_(
            BillingRecord.insurance_carrier.in_(secondary_payer_codes),
            BillingRecord.primary_payment > 0,
            or_(
                BillingRecord.secondary_payment.is_(None),
                BillingRecord.secondary_payment == 0,
            ),
            BillingRecord.denial_status.is_(None),
        )
    ).scalar() or 0

    return {
        "flagged": flagged_count,
        "secondary_payers": list(secondary_payer_codes),
        "description": f"{flagged_count} claims may need secondary billing",
    }


def _update_filing_deadlines() -> dict:
    """Check for claims approaching filing deadlines."""
    today = date.today()
    thirty_days = today + timedelta(days=30)

    approaching_count = db.session.query(func.count(BillingRecord.id)).filter(
        and_(
            BillingRecord.appeal_deadline.is_not(None),
            BillingRecord.appeal_deadline <= thirty_days,
            BillingRecord.appeal_deadline >= today,
            BillingRecord.denial_status.is_not(None),
        )
    ).scalar() or 0

    urgent_count = db.session.query(func.count(BillingRecord.id)).filter(
        and_(
            BillingRecord.appeal_deadline.is_not(None),
            BillingRecord.appeal_deadline <= today + timedelta(days=7),
            BillingRecord.appeal_deadline >= today,
            BillingRecord.denial_status.is_not(None),
        )
    ).scalar() or 0

    expired_count = db.session.query(func.count(BillingRecord.id)).filter(
        and_(
            BillingRecord.appeal_deadline.is_not(None),
            BillingRecord.appeal_deadline < today,
            BillingRecord.denial_status.is_not(None),
        )
    ).scalar() or 0

    return {
        "approaching_30d": approaching_count,
        "urgent_7d": urgent_count,
        "expired": expired_count,
        "description": f"Filing deadlines: {urgent_count} urgent (<7d), {approaching_count} approaching (<30d), {expired_count} expired",
    }
