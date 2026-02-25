"""Payment Pattern Learning (SM-07).

Tracks actual payment amounts per carrier/modality to detect underpayment
trends and auto-suggest fee schedule updates.
"""

from datetime import date, timedelta

from sqlalchemy import func

from app.models import db, BillingRecord, FeeSchedule


# ── SM-07a: Payment Pattern Tracking ────────────────────────────

def get_payment_patterns(days=90):
    """Aggregate actual payments per carrier/modality over recent period.

    Returns list of patterns with avg, median-proxy, count, and trend info.
    """
    cutoff = date.today() - timedelta(days=days)

    results = db.session.query(
        BillingRecord.insurance_carrier,
        BillingRecord.modality,
        func.count(BillingRecord.id).label("count"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
        func.min(BillingRecord.total_payment).label("min_payment"),
        func.max(BillingRecord.total_payment).label("max_payment"),
        func.sum(BillingRecord.total_payment).label("total_revenue"),
    ).filter(
        BillingRecord.total_payment > 0,
        BillingRecord.service_date >= cutoff,
    ).group_by(
        BillingRecord.insurance_carrier, BillingRecord.modality,
    ).having(func.count(BillingRecord.id) >= 3).all()

    # Get fee schedule for comparison
    fee_map = {}
    for fs in FeeSchedule.query.all():
        fee_map[(fs.payer_code, fs.modality)] = fs.expected_rate
        if fs.payer_code == "DEFAULT":
            fee_map.setdefault(("_default", fs.modality), fs.expected_rate)

    patterns = []
    for r in results:
        expected = fee_map.get(
            (r.insurance_carrier, r.modality),
            fee_map.get(("_default", r.modality), 0)
        )

        variance_pct = 0
        if expected > 0:
            variance_pct = round(((r.avg_payment - expected) / expected) * 100, 1)

        patterns.append({
            "carrier": r.insurance_carrier,
            "modality": r.modality,
            "count": r.count,
            "avg_payment": round(r.avg_payment, 2),
            "min_payment": round(r.min_payment, 2),
            "max_payment": round(r.max_payment, 2),
            "total_revenue": round(r.total_revenue, 2),
            "expected_rate": expected,
            "variance_pct": variance_pct,
            "status": _classify_pattern(variance_pct),
        })

    patterns.sort(key=lambda x: x["variance_pct"])
    return patterns


def _classify_pattern(variance_pct):
    """Classify a payment pattern based on variance from expected."""
    if variance_pct <= -20:
        return "UNDERPAYING"
    elif variance_pct <= -10:
        return "BELOW_EXPECTED"
    elif variance_pct >= 10:
        return "ABOVE_EXPECTED"
    return "NORMAL"


# ── SM-07b: Fee Schedule Suggestions ────────────────────────────

def suggest_fee_updates(min_count=10, days=180):
    """Suggest fee schedule updates based on actual payment patterns.

    Returns updates where actual avg differs from expected by >15%.
    """
    cutoff = date.today() - timedelta(days=days)

    results = db.session.query(
        BillingRecord.insurance_carrier,
        BillingRecord.modality,
        func.count(BillingRecord.id).label("count"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
    ).filter(
        BillingRecord.total_payment > 0,
        BillingRecord.service_date >= cutoff,
    ).group_by(
        BillingRecord.insurance_carrier, BillingRecord.modality,
    ).having(func.count(BillingRecord.id) >= min_count).all()

    suggestions = []
    for r in results:
        fs = FeeSchedule.query.filter_by(
            payer_code=r.insurance_carrier, modality=r.modality
        ).first()
        current_rate = fs.expected_rate if fs else None

        if current_rate and current_rate > 0:
            diff_pct = abs(r.avg_payment - current_rate) / current_rate * 100
            if diff_pct > 15:
                suggestions.append({
                    "carrier": r.insurance_carrier,
                    "modality": r.modality,
                    "current_rate": current_rate,
                    "suggested_rate": round(r.avg_payment, 2),
                    "sample_size": r.count,
                    "diff_pct": round(diff_pct, 1),
                    "direction": "UP" if r.avg_payment > current_rate else "DOWN",
                })
        elif not fs:
            # No fee schedule entry exists — suggest creating one
            suggestions.append({
                "carrier": r.insurance_carrier,
                "modality": r.modality,
                "current_rate": None,
                "suggested_rate": round(r.avg_payment, 2),
                "sample_size": r.count,
                "diff_pct": None,
                "direction": "NEW",
            })

    suggestions.sort(key=lambda x: x.get("diff_pct") or 0, reverse=True)
    return suggestions


def apply_fee_update(carrier, modality, new_rate):
    """Apply a suggested fee schedule update."""
    fs = FeeSchedule.query.filter_by(payer_code=carrier, modality=modality).first()
    if fs:
        fs.expected_rate = new_rate
    else:
        fs = FeeSchedule(payer_code=carrier, modality=modality, expected_rate=new_rate)
        db.session.add(fs)
    db.session.commit()
    return {"status": "updated", "carrier": carrier, "modality": modality, "rate": new_rate}
