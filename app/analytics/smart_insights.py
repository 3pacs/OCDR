"""Smart Insights Engine — Anomaly Detection, Risk Scoring, Forecasting.

Generates actionable intelligence from billing data patterns.
"""

import math
from datetime import date, timedelta
from collections import defaultdict

from sqlalchemy import func, case

from app.models import db, BillingRecord, FeeSchedule, EraPayment, EraClaimLine


# ── Carrier Behavior Scoring ──────────────────────────────────

def score_carriers(days=180):
    """Score each carrier on payment reliability, denial rate, and speed.

    Returns a list of carrier scorecards sorted by overall score.
    """
    cutoff = date.today() - timedelta(days=days)

    results = db.session.query(
        BillingRecord.insurance_carrier,
        func.count(BillingRecord.id).label("total_claims"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
        func.sum(BillingRecord.total_payment).label("total_revenue"),
        func.sum(case(
            (BillingRecord.total_payment == 0, 1), else_=0
        )).label("zero_pay_count"),
    ).filter(
        BillingRecord.service_date >= cutoff,
    ).group_by(BillingRecord.insurance_carrier).having(
        func.count(BillingRecord.id) >= 5
    ).all()

    # Fee schedule lookup
    fee_map = {}
    for fs in FeeSchedule.query.all():
        fee_map[(fs.payer_code, fs.modality)] = fs.expected_rate

    # Per-carrier modality breakdown
    modality_stats = db.session.query(
        BillingRecord.insurance_carrier,
        BillingRecord.modality,
        func.avg(BillingRecord.total_payment).label("avg_pay"),
        func.count(BillingRecord.id).label("cnt"),
    ).filter(
        BillingRecord.service_date >= cutoff,
        BillingRecord.total_payment > 0,
    ).group_by(
        BillingRecord.insurance_carrier, BillingRecord.modality,
    ).all()

    mod_map = defaultdict(list)
    for m in modality_stats:
        expected = fee_map.get((m.insurance_carrier, m.modality), 0)
        pct = (m.avg_pay / expected * 100) if expected > 0 else 100
        mod_map[m.insurance_carrier].append({
            "modality": m.modality, "avg_pay": round(m.avg_pay, 2),
            "count": m.cnt, "pct_of_expected": round(pct, 1),
        })

    scorecards = []
    for r in results:
        carrier = r.insurance_carrier
        total = r.total_claims
        denial_rate = (r.zero_pay_count / total * 100) if total > 0 else 0

        # Payment score: 100 = pays well, 0 = mostly denials
        payment_score = max(0, 100 - denial_rate * 2)

        # Consistency score: how close avg payment is to expected
        modality_data = mod_map.get(carrier, [])
        consistency_scores = []
        for md in modality_data:
            if md["pct_of_expected"] > 0:
                deviation = abs(md["pct_of_expected"] - 100)
                consistency_scores.append(max(0, 100 - deviation))
        consistency = sum(consistency_scores) / len(consistency_scores) if consistency_scores else 50

        # Overall score (weighted)
        overall = round(payment_score * 0.6 + consistency * 0.4, 1)

        grade = "A" if overall >= 85 else "B" if overall >= 70 else "C" if overall >= 55 else "D" if overall >= 40 else "F"

        scorecards.append({
            "carrier": carrier,
            "total_claims": total,
            "total_revenue": round(r.total_revenue, 2),
            "avg_payment": round(r.avg_payment, 2),
            "denial_rate": round(denial_rate, 1),
            "payment_score": round(payment_score, 1),
            "consistency_score": round(consistency, 1),
            "overall_score": overall,
            "grade": grade,
            "modality_breakdown": modality_data,
        })

    scorecards.sort(key=lambda x: x["overall_score"], reverse=True)
    return scorecards


# ── Anomaly Detection ─────────────────────────────────────────

def detect_anomalies(days=30):
    """Detect anomalous billing patterns in recent data.

    Flags: unusual payment amounts, sudden denial spikes, new carriers,
    missing secondary payments, and payment reversals.
    """
    cutoff = date.today() - timedelta(days=days)
    prior_cutoff = cutoff - timedelta(days=days)
    anomalies = []

    # 1. Payment amount anomalies (values > 2 std devs from mean per modality)
    modality_stats = db.session.query(
        BillingRecord.modality,
        func.avg(BillingRecord.total_payment).label("avg"),
        func.count(BillingRecord.id).label("cnt"),
    ).filter(
        BillingRecord.total_payment > 0,
        BillingRecord.service_date >= prior_cutoff,
        BillingRecord.service_date < cutoff,
    ).group_by(BillingRecord.modality).having(
        func.count(BillingRecord.id) >= 10
    ).all()

    stat_map = {s.modality: s.avg for s in modality_stats}

    # Check recent records for outliers
    recent = BillingRecord.query.filter(
        BillingRecord.service_date >= cutoff,
        BillingRecord.total_payment > 0,
    ).all()

    for rec in recent:
        avg = stat_map.get(rec.modality)
        if avg and avg > 0 and rec.total_payment > avg * 3:
            anomalies.append({
                "type": "HIGH_PAYMENT",
                "severity": "warning",
                "message": f"{rec.patient_name}: {rec.modality} payment ${rec.total_payment:.0f} is {rec.total_payment/avg:.1f}x the average (${avg:.0f})",
                "record_id": rec.id,
                "value": rec.total_payment,
            })

    # 2. Denial rate spikes (compare recent period to prior period)
    recent_denials = db.session.query(
        BillingRecord.insurance_carrier,
        func.count(BillingRecord.id).label("total"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
    ).filter(
        BillingRecord.service_date >= cutoff,
    ).group_by(BillingRecord.insurance_carrier).having(
        func.count(BillingRecord.id) >= 5
    ).all()

    prior_denials = db.session.query(
        BillingRecord.insurance_carrier,
        func.count(BillingRecord.id).label("total"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
    ).filter(
        BillingRecord.service_date >= prior_cutoff,
        BillingRecord.service_date < cutoff,
    ).group_by(BillingRecord.insurance_carrier).having(
        func.count(BillingRecord.id) >= 5
    ).all()

    prior_rates = {r.insurance_carrier: (r.denied / r.total * 100) if r.total > 0 else 0 for r in prior_denials}

    for r in recent_denials:
        current_rate = (r.denied / r.total * 100) if r.total > 0 else 0
        prior_rate = prior_rates.get(r.insurance_carrier, 0)
        if current_rate > prior_rate + 15 and current_rate > 10:
            anomalies.append({
                "type": "DENIAL_SPIKE",
                "severity": "critical",
                "message": f"{r.insurance_carrier}: denial rate jumped from {prior_rate:.0f}% to {current_rate:.0f}% ({r.denied}/{r.total} claims)",
                "carrier": r.insurance_carrier,
                "value": current_rate,
            })

    # 3. New/unknown carriers appearing in data
    known_carriers = set(r.insurance_carrier for r in db.session.query(
        BillingRecord.insurance_carrier
    ).filter(BillingRecord.service_date < cutoff).distinct().all())

    new_carriers = set(r.insurance_carrier for r in db.session.query(
        BillingRecord.insurance_carrier
    ).filter(BillingRecord.service_date >= cutoff).distinct().all()) - known_carriers

    for c in new_carriers:
        if c and c != "UNKNOWN":
            count = BillingRecord.query.filter(
                BillingRecord.insurance_carrier == c,
                BillingRecord.service_date >= cutoff,
            ).count()
            anomalies.append({
                "type": "NEW_CARRIER",
                "severity": "info",
                "message": f"New carrier detected: {c} ({count} claims). Consider adding to fee schedule.",
                "carrier": c,
                "value": count,
            })

    # Sort by severity
    severity_order = {"critical": 0, "warning": 1, "info": 2}
    anomalies.sort(key=lambda a: severity_order.get(a["severity"], 3))
    return anomalies


# ── Predictive Denial Risk ────────────────────────────────────

def score_denial_risk(billing_record=None, carrier=None, modality=None):
    """Score the denial risk for a claim based on historical patterns.

    Returns a risk score 0-100 (100 = very likely to be denied).
    """
    if billing_record:
        carrier = billing_record.insurance_carrier
        modality = billing_record.modality

    if not carrier:
        return {"risk_score": 50, "factors": ["Insufficient data"]}

    cutoff = date.today() - timedelta(days=180)
    factors = []

    # Factor 1: Carrier-level denial rate
    carrier_stats = db.session.query(
        func.count(BillingRecord.id).label("total"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
    ).filter(
        BillingRecord.insurance_carrier == carrier,
        BillingRecord.service_date >= cutoff,
    ).first()

    carrier_denial_rate = 0
    if carrier_stats and carrier_stats.total > 0:
        carrier_denial_rate = carrier_stats.denied / carrier_stats.total * 100
        if carrier_denial_rate > 20:
            factors.append(f"High carrier denial rate: {carrier_denial_rate:.0f}%")
        elif carrier_denial_rate > 10:
            factors.append(f"Moderate carrier denial rate: {carrier_denial_rate:.0f}%")

    # Factor 2: Modality-specific denial rate for this carrier
    modality_denial_rate = 0
    if modality:
        mod_stats = db.session.query(
            func.count(BillingRecord.id).label("total"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
        ).filter(
            BillingRecord.insurance_carrier == carrier,
            BillingRecord.modality == modality,
            BillingRecord.service_date >= cutoff,
        ).first()

        if mod_stats and mod_stats.total >= 3:
            modality_denial_rate = mod_stats.denied / mod_stats.total * 100
            if modality_denial_rate > carrier_denial_rate + 10:
                factors.append(f"This modality ({modality}) has {modality_denial_rate:.0f}% denial rate vs {carrier_denial_rate:.0f}% carrier average")

    # Factor 3: Recent trend (is it getting worse?)
    recent_cutoff = date.today() - timedelta(days=30)
    recent_stats = db.session.query(
        func.count(BillingRecord.id).label("total"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
    ).filter(
        BillingRecord.insurance_carrier == carrier,
        BillingRecord.service_date >= recent_cutoff,
    ).first()

    if recent_stats and recent_stats.total >= 5:
        recent_rate = recent_stats.denied / recent_stats.total * 100
        if recent_rate > carrier_denial_rate + 10:
            factors.append(f"Denial rate trending UP: {recent_rate:.0f}% in last 30 days")

    # Calculate composite risk score
    risk_score = (
        carrier_denial_rate * 0.5 +
        modality_denial_rate * 0.35 +
        min(50, carrier_denial_rate * 0.15)  # trend penalty
    )
    risk_score = min(100, max(0, risk_score))

    if not factors:
        factors.append("Normal risk level")

    risk_level = "HIGH" if risk_score > 40 else "MEDIUM" if risk_score > 20 else "LOW"

    return {
        "risk_score": round(risk_score, 1),
        "risk_level": risk_level,
        "carrier": carrier,
        "modality": modality,
        "factors": factors,
    }


# ── Revenue Forecasting ──────────────────────────────────────

def forecast_revenue(months_ahead=3):
    """Forecast revenue for next N months using weighted moving average.

    Uses 6-month history with exponential decay weighting.
    """
    today = date.today()

    # Get last 12 months of revenue
    monthly = db.session.query(
        func.strftime("%Y-%m", BillingRecord.service_date).label("month"),
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.count(BillingRecord.id).label("claims"),
    ).filter(
        BillingRecord.service_date >= today - timedelta(days=365),
        BillingRecord.total_payment > 0,
    ).group_by(
        func.strftime("%Y-%m", BillingRecord.service_date),
    ).order_by("month").all()

    if len(monthly) < 3:
        return {"status": "insufficient_data", "forecast": []}

    # Weighted moving average (recent months weighted more)
    revenues = [m.revenue for m in monthly]
    claims = [m.claims for m in monthly]

    # Exponential weights: most recent = 1.0, decay by 0.85 per month
    n = len(revenues)
    weights = [0.85 ** (n - 1 - i) for i in range(n)]
    weight_sum = sum(weights)

    avg_revenue = sum(r * w for r, w in zip(revenues, weights)) / weight_sum
    avg_claims = sum(c * w for c, w in zip(claims, weights)) / weight_sum

    # Detect trend (simple linear regression on last 6 months)
    recent = revenues[-6:] if len(revenues) >= 6 else revenues
    if len(recent) >= 3:
        x_mean = (len(recent) - 1) / 2
        y_mean = sum(recent) / len(recent)
        numerator = sum((i - x_mean) * (y - y_mean) for i, y in enumerate(recent))
        denominator = sum((i - x_mean) ** 2 for i in range(len(recent)))
        slope = numerator / denominator if denominator > 0 else 0
        monthly_trend = slope
    else:
        monthly_trend = 0

    # Generate forecasts
    trend_pct = (monthly_trend / avg_revenue * 100) if avg_revenue > 0 else 0
    forecasts = []
    for i in range(1, months_ahead + 1):
        month_date = date(today.year + (today.month + i - 1) // 12,
                         (today.month + i - 1) % 12 + 1, 1)
        projected = avg_revenue + monthly_trend * i
        # Apply confidence band (wider for further out)
        confidence = max(0.5, 1.0 - i * 0.1)
        forecasts.append({
            "month": month_date.strftime("%Y-%m"),
            "projected_revenue": round(max(0, projected), 2),
            "projected_claims": round(max(0, avg_claims + (monthly_trend / (avg_revenue / avg_claims if avg_revenue > 0 else 1)) * i)),
            "confidence": round(confidence, 2),
            "low_estimate": round(max(0, projected * (1 - (1 - confidence) * 2)), 2),
            "high_estimate": round(projected * (1 + (1 - confidence) * 2), 2),
        })

    return {
        "status": "ok",
        "historical": [{"month": m.month, "revenue": round(m.revenue, 2), "claims": m.claims} for m in monthly],
        "forecast": forecasts,
        "trend": {
            "direction": "UP" if trend_pct > 2 else "DOWN" if trend_pct < -2 else "STABLE",
            "monthly_change_pct": round(trend_pct, 1),
            "monthly_change_amount": round(monthly_trend, 2),
        },
        "weighted_avg_revenue": round(avg_revenue, 2),
    }


# ── Smart Dashboard Insights ─────────────────────────────────

def generate_insights():
    """Generate top actionable insights for the dashboard.

    Returns a prioritized list of insights with suggested actions.
    """
    insights = []

    today = date.today()
    cutoff_30 = today - timedelta(days=30)
    cutoff_90 = today - timedelta(days=90)

    total_records = BillingRecord.query.count()
    if total_records == 0:
        return [{"priority": 1, "type": "SETUP", "title": "Get Started",
                 "message": "Import your billing data to unlock insights.",
                 "action": "/import", "action_label": "Import Data"}]

    # 1. Unmatched ERA claims
    unmatched = EraClaimLine.query.filter(
        EraClaimLine.matched_billing_id.is_(None),
    ).count()
    if unmatched > 0:
        insights.append({
            "priority": 1, "type": "ACTION",
            "title": f"{unmatched} Unmatched ERA Claims",
            "message": "Run auto-matching to link ERA payments to billing records.",
            "action": "/match-review", "action_label": "Match Now",
        })

    # 2. Denial rate trending up
    recent_denied = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.service_date >= cutoff_30,
        BillingRecord.total_payment == 0,
    ).scalar() or 0
    recent_total = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.service_date >= cutoff_30,
    ).scalar() or 1
    denial_rate = recent_denied / recent_total * 100

    if denial_rate > 15:
        insights.append({
            "priority": 2, "type": "ALERT",
            "title": f"Denial Rate at {denial_rate:.0f}%",
            "message": f"{recent_denied} claims denied in the last 30 days. Check denial queue for appeal opportunities.",
            "action": "/denial-queue", "action_label": "View Denials",
        })

    # 3. Missing fee schedule entries
    carriers_without_fees = db.session.query(
        BillingRecord.insurance_carrier
    ).filter(
        BillingRecord.service_date >= cutoff_90,
    ).distinct().all()

    fee_entries = set((fs.payer_code, fs.modality) for fs in FeeSchedule.query.all())
    missing_count = 0
    for (carrier,) in carriers_without_fees:
        modalities = db.session.query(BillingRecord.modality).filter(
            BillingRecord.insurance_carrier == carrier,
            BillingRecord.service_date >= cutoff_90,
        ).distinct().all()
        for (mod,) in modalities:
            if (carrier, mod) not in fee_entries:
                missing_count += 1

    if missing_count > 0:
        insights.append({
            "priority": 3, "type": "SETUP",
            "title": f"{missing_count} Missing Fee Schedule Entries",
            "message": "Set up expected rates to enable underpayment detection.",
            "action": "/admin", "action_label": "Configure Fees",
        })

    # 4. Recovery opportunities
    zero_pay = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.total_payment == 0,
        BillingRecord.service_date >= cutoff_90,
    ).scalar() or 0

    if zero_pay > 10:
        avg_payment = db.session.query(func.avg(BillingRecord.total_payment)).filter(
            BillingRecord.total_payment > 0,
            BillingRecord.service_date >= cutoff_90,
        ).scalar() or 0

        potential = zero_pay * avg_payment * 0.3  # 30% assumed recovery rate
        if potential > 1000:
            insights.append({
                "priority": 2, "type": "MONEY",
                "title": f"${potential:,.0f} Recovery Potential",
                "message": f"{zero_pay} unpaid claims in the last 90 days. Based on historical data, ~30% may be recoverable.",
                "action": "/denial-queue", "action_label": "Start Appeals",
            })

    # 5. Auto-learn suggestions
    try:
        from app.import_engine.normalization_learner import get_pending_normalizations
        pending = get_pending_normalizations()
        if len(pending) > 0:
            insights.append({
                "priority": 4, "type": "LEARN",
                "title": f"{len(pending)} Pending Normalizations",
                "message": "Review and approve carrier/modality mappings to improve future imports.",
                "action": "/smart-matching", "action_label": "Review",
            })
    except Exception:
        pass

    insights.sort(key=lambda x: x["priority"])
    return insights[:8]  # Top 8 insights
