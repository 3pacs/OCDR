"""Denial Intelligence — Recovery Learning & Pattern Detection (SM-03, SM-12).

Tracks appeal outcomes to learn actual recovery rates per carrier + denial reason.
Detects recurring denial patterns for proactive prevention.
"""

from datetime import date, datetime

from sqlalchemy import func

from app.models import db, DenialOutcome, BillingRecord, FeeSchedule


# ── Constants ────────────────────────────────────────────────────

MIN_OUTCOMES_FOR_LEARNING = 10
PATTERN_MIN_COUNT = 3


# ── SM-03a: Denial Outcome Tracking ─────────────────────────────

def record_denial_outcome(billing_record_id, outcome, recovered_amount=0.0):
    """Record a denial resolution outcome for learning.

    Args:
        billing_record_id: The billing record that was denied
        outcome: RECOVERED, PARTIAL, or WRITTEN_OFF
        recovered_amount: Actual dollars recovered
    """
    record = db.session.get(BillingRecord, billing_record_id)
    if not record:
        return None

    # Get expected amount from fee schedule
    fs = FeeSchedule.query.filter_by(
        payer_code=record.insurance_carrier, modality=record.modality
    ).first()
    if not fs:
        fs = FeeSchedule.query.filter_by(
            payer_code="DEFAULT", modality=record.modality
        ).first()
    expected = fs.expected_rate if fs else 500.0

    days_old = (date.today() - record.service_date).days if record.service_date else 0

    denial_out = DenialOutcome(
        billing_record_id=billing_record_id,
        carrier=record.insurance_carrier,
        denial_reason=record.denial_reason_code,
        modality=record.modality,
        days_old_at_appeal=days_old,
        outcome=outcome,
        recovered_amount=recovered_amount,
        expected_amount=expected,
    )
    db.session.add(denial_out)
    db.session.commit()
    return denial_out.id


# ── SM-03b: Recovery Rate Calculator ────────────────────────────

def get_recovery_rates():
    """Compute actual recovery rates per carrier + denial reason.

    Returns dict: {(carrier, reason): {rate, probability, count, avg_recovered}}
    """
    results = db.session.query(
        DenialOutcome.carrier,
        DenialOutcome.denial_reason,
        func.count(DenialOutcome.id).label("total"),
        func.sum(DenialOutcome.recovered_amount).label("total_recovered"),
        func.sum(DenialOutcome.expected_amount).label("total_expected"),
    ).group_by(
        DenialOutcome.carrier, DenialOutcome.denial_reason
    ).all()

    rates = {}
    for r in results:
        if r.total < MIN_OUTCOMES_FOR_LEARNING:
            continue

        # Count recoveries (any amount > 0)
        recovered_count = db.session.query(func.count(DenialOutcome.id)).filter(
            DenialOutcome.carrier == r.carrier,
            DenialOutcome.denial_reason == r.denial_reason,
            DenialOutcome.recovered_amount > 0,
        ).scalar() or 0

        total_recovered = r.total_recovered or 0
        total_expected = r.total_expected or 1

        rates[(r.carrier, r.denial_reason)] = {
            "recovery_rate": round(total_recovered / total_expected, 4) if total_expected > 0 else 0,
            "recovery_probability": round(recovered_count / r.total, 4) if r.total > 0 else 0,
            "sample_size": r.total,
            "avg_recovered": round(total_recovered / r.total, 2) if r.total > 0 else 0,
            "total_recovered": round(total_recovered, 2),
        }

    return rates


def get_recovery_rates_list():
    """Get recovery rates as a list for API response."""
    rates = get_recovery_rates()
    return [{
        "carrier": carrier,
        "denial_reason": reason,
        **data,
    } for (carrier, reason), data in sorted(rates.items())]


# ── SM-03c: Smart Recoverability Scoring ─────────────────────────

def smart_recoverability_score(record, days_old, fee_map=None):
    """Compute recoverability using learned rates when available.

    Falls back to the original formula when insufficient data.
    """
    # Try learned rate first
    rates = get_recovery_rates()
    key = (record.insurance_carrier, record.denial_reason_code)
    learned = rates.get(key)

    # Get expected value
    if fee_map:
        expected = fee_map.get(
            (record.insurance_carrier, record.modality),
            fee_map.get(("_default", record.modality), 500.0)
        )
    else:
        fs = FeeSchedule.query.filter_by(
            payer_code=record.insurance_carrier, modality=record.modality
        ).first()
        if not fs:
            fs = FeeSchedule.query.filter_by(
                payer_code="DEFAULT", modality=record.modality
            ).first()
        expected = fs.expected_rate if fs else 500.0

    if learned:
        # Smart scoring: expected * probability * rate * age_decay
        # Age decay learned from data: compute avg days_old for recoveries
        avg_recovery_days = _avg_recovery_days(record.insurance_carrier, record.denial_reason_code)
        if avg_recovery_days and avg_recovery_days > 0:
            age_factor = max(0, 1 - (days_old / (avg_recovery_days * 2)))
        else:
            age_factor = max(0, 1 - (days_old / 365))

        return expected * learned["recovery_probability"] * learned["recovery_rate"] * age_factor

    # Fallback: original formula
    return expected * max(0, 1 - (days_old / 365))


def _avg_recovery_days(carrier, denial_reason):
    """Get average days_old_at_appeal for successful recoveries."""
    avg = db.session.query(func.avg(DenialOutcome.days_old_at_appeal)).filter(
        DenialOutcome.carrier == carrier,
        DenialOutcome.denial_reason == denial_reason,
        DenialOutcome.recovered_amount > 0,
    ).scalar()
    return avg


# ── SM-12: Denial Pattern Detection ─────────────────────────────

def detect_denial_patterns():
    """Identify recurring denial patterns (carrier + reason + modality).

    Returns patterns with 3+ occurrences, sorted by frequency.
    """
    results = db.session.query(
        BillingRecord.insurance_carrier,
        BillingRecord.denial_reason_code,
        BillingRecord.modality,
        func.count(BillingRecord.id).label("count"),
        func.min(BillingRecord.service_date).label("first_seen"),
        func.max(BillingRecord.service_date).label("last_seen"),
    ).filter(
        BillingRecord.total_payment == 0,
        BillingRecord.denial_reason_code.isnot(None),
    ).group_by(
        BillingRecord.insurance_carrier,
        BillingRecord.denial_reason_code,
        BillingRecord.modality,
    ).having(
        func.count(BillingRecord.id) >= PATTERN_MIN_COUNT
    ).order_by(func.count(BillingRecord.id).desc()).all()

    patterns = []
    for r in results:
        # Check if we have learned recovery rate for this pattern
        rates = get_recovery_rates()
        learned = rates.get((r.insurance_carrier, r.denial_reason_code))

        suggestion = _suggest_action(r.denial_reason_code, r.count, learned)

        patterns.append({
            "carrier": r.insurance_carrier,
            "denial_reason": r.denial_reason_code,
            "modality": r.modality,
            "count": r.count,
            "first_seen": r.first_seen.isoformat() if r.first_seen else None,
            "last_seen": r.last_seen.isoformat() if r.last_seen else None,
            "recovery_rate": learned["recovery_rate"] if learned else None,
            "suggestion": suggestion,
        })

    return patterns


def _suggest_action(reason_code, count, learned_rate):
    """Generate a suggestion for handling a denial pattern."""
    if not reason_code:
        return "Review denial details"

    code = str(reason_code).strip()

    # Known actionable codes
    suggestions = {
        "16": "Missing information — check pre-authorization requirements",
        "18": "Duplicate claim — review billing procedures for this carrier",
        "29": "Filing deadline expired — prioritize timely submissions",
        "49": "Medical necessity — ensure proper documentation/coding",
        "50": "Medical necessity — pre-cert or peer-to-peer review recommended",
        "96": "Non-covered — verify coverage before scheduling",
        "197": "Missing pre-authorization — implement pre-cert workflow",
    }

    if code in suggestions:
        base = suggestions[code]
    else:
        base = f"Review denial reason code {code}"

    if learned_rate and learned_rate["recovery_probability"] < 0.2:
        base += " (low recovery likelihood — consider write-off)"
    elif learned_rate and learned_rate["recovery_probability"] > 0.7:
        base += " (high recovery likelihood — prioritize appeal)"

    if count >= 10:
        base += f" — {count} occurrences suggest systemic issue"

    return base
