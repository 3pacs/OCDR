"""Recommendations Engine.

Analyzes the knowledge graph and billing data to generate actionable
insights and practice improvement suggestions.
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import String, or_, func, case, extract

from app.models import db, BillingRecord, EraClaimLine, Payer, FeeSchedule, InsightLog
from app.revenue.writeoff_filter import not_written_off


def generate_all_recommendations() -> list[dict]:
    """Run all recommendation analyzers and return sorted results."""
    recommendations = []
    analyzers = [
        _analyze_denial_patterns,
        _analyze_payer_underpayment_patterns,
        _analyze_secondary_gaps,
        _analyze_payer_trends,
        _analyze_physician_denial_rates,
        _analyze_filing_risks,
        _analyze_modality_pricing_gaps,
        _analyze_process_improvements,
    ]
    for analyzer in analyzers:
        try:
            recommendations.extend(analyzer())
        except Exception as e:
            recommendations.append({
                "category": "SYSTEM", "severity": "LOW",
                "title": f"Analyzer error: {analyzer.__name__}",
                "description": str(e), "recommendation": "Check system logs",
                "estimated_impact": 0, "affected_count": 0,
            })
    recommendations.sort(key=lambda r: r.get("estimated_impact", 0) or 0, reverse=True)
    return recommendations


def _analyze_denial_patterns() -> list[dict]:
    results = []
    rows = db.session.query(
        BillingRecord.insurance_carrier.label("carrier"),
        BillingRecord.modality.label("modality"),
        func.count().label("total"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
        func.sum(case((BillingRecord.total_payment > 0, BillingRecord.total_payment), else_=0)).label("avg_paid_rev"),
    ).filter(not_written_off()).group_by(
        BillingRecord.insurance_carrier, BillingRecord.modality
    ).having(func.count() >= 10).all()

    for r in rows:
        denial_rate = r.denied / r.total if r.total else 0
        if denial_rate > 0.15 and r.denied >= 5:
            avg_claim = float(r.avg_paid_rev or 0) / max(r.total - r.denied, 1)
            impact = round(r.denied * avg_claim, 2)
            severity = "CRITICAL" if denial_rate > 0.4 else "HIGH" if denial_rate > 0.25 else "MEDIUM"
            results.append({
                "category": "DENIAL_PATTERN", "severity": severity,
                "title": f"{r.carrier} denies {round(denial_rate*100)}% of {r.modality} claims",
                "description": f"{r.denied} of {r.total} {r.modality} claims from {r.carrier} are denied. Avg paid claim: ${avg_claim:,.0f}.",
                "recommendation": f"Investigate {r.carrier} {r.modality} denial reasons. Fixing half could recover ~${impact/2:,.0f}.",
                "estimated_impact": impact, "affected_count": r.denied,
                "entity_type": "PAYER", "entity_id": r.carrier,
                "data": {"carrier": r.carrier, "modality": r.modality, "denial_rate": round(denial_rate * 100, 1)},
            })
    return results


def _analyze_payer_underpayment_patterns() -> list[dict]:
    results = []
    fee_map = {}
    for fs in FeeSchedule.query.all():
        fee_map[(fs.payer_code, fs.modality)] = float(fs.expected_rate)

    rows = db.session.query(
        BillingRecord.insurance_carrier.label("carrier"),
        BillingRecord.modality.label("modality"),
        func.count().label("count"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
    ).filter(BillingRecord.total_payment > 0, not_written_off()).group_by(
        BillingRecord.insurance_carrier, BillingRecord.modality
    ).having(func.count() >= 10).all()

    for r in rows:
        expected = fee_map.get((r.carrier, r.modality)) or fee_map.get(("DEFAULT", r.modality))
        if not expected:
            continue
        avg_pay = float(r.avg_payment or 0)
        pay_rate = avg_pay / expected if expected else 1.0
        if pay_rate < 0.70:
            total_gap = (expected - avg_pay) * r.count
            results.append({
                "category": "UNDERPAYMENT",
                "severity": "HIGH" if pay_rate < 0.50 else "MEDIUM",
                "title": f"{r.carrier} pays {round(pay_rate*100)}% of expected for {r.modality}",
                "description": f"{r.carrier} averages ${avg_pay:,.0f} vs expected ${expected:,.0f} ({r.count} claims). Gap: ${total_gap:,.0f}.",
                "recommendation": f"Review {r.carrier} contract terms for {r.modality}.",
                "estimated_impact": round(total_gap, 2), "affected_count": r.count,
                "entity_type": "PAYER", "entity_id": r.carrier,
                "data": {"carrier": r.carrier, "modality": r.modality, "pay_rate_pct": round(pay_rate * 100, 1)},
            })
    return results


def _analyze_secondary_gaps() -> list[dict]:
    results = []
    secondary_carriers = {p.code for p in Payer.query.filter_by(expected_has_secondary=True).all()}
    secondary_carriers.update({"M/M"})

    rows = db.session.query(
        BillingRecord.insurance_carrier.label("carrier"),
        func.count().label("count"),
        func.sum(BillingRecord.primary_payment).label("total_primary"),
    ).filter(
        BillingRecord.insurance_carrier.in_(secondary_carriers),
        BillingRecord.primary_payment > 0,
        BillingRecord.secondary_payment == 0,
        not_written_off(),
    ).group_by(BillingRecord.insurance_carrier).having(func.count() >= 10).all()

    for row in rows:
        est_secondary = float(row.total_primary or 0) * 0.335
        results.append({
            "category": "SECONDARY_MISSING",
            "severity": "HIGH" if est_secondary > 100000 else "MEDIUM",
            "title": f"{row.carrier}: {row.count} claims missing secondary payment",
            "description": f"{row.count} claims with {row.carrier} primary (${float(row.total_primary or 0):,.0f}) have $0 secondary. Est. ~${est_secondary:,.0f}.",
            "recommendation": f"Batch-file secondary claims for {row.count} {row.carrier} records.",
            "estimated_impact": round(est_secondary, 2), "affected_count": row.count,
            "entity_type": "PAYER", "entity_id": row.carrier,
            "data": {"carrier": row.carrier, "missing_count": row.count},
        })
    return results


def _analyze_payer_trends() -> list[dict]:
    results = []
    try:
        rows = db.session.query(
            BillingRecord.insurance_carrier.label("carrier"),
            func.coalesce(
                BillingRecord.service_year,
                extract("year", BillingRecord.service_date).cast(String),
            ).label("year"),
            func.count().label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        ).filter(BillingRecord.service_date.isnot(None), not_written_off()).group_by(
            BillingRecord.insurance_carrier, BillingRecord.service_year
        ).all()
    except Exception:
        return results

    carrier_years = defaultdict(dict)
    for r in rows:
        year = str(r.year) if r.year else None
        if year:
            carrier_years[r.carrier][year] = {"count": r.count, "revenue": float(r.revenue or 0)}

    for carrier, years in carrier_years.items():
        sorted_years = sorted(years.keys())
        if len(sorted_years) < 2:
            continue
        latest, prev = sorted_years[-1], sorted_years[-2]
        latest_rev, prev_rev = years[latest]["revenue"], years[prev]["revenue"]
        if prev_rev <= 0:
            continue
        rev_change = (latest_rev - prev_rev) / prev_rev
        if rev_change < -0.30 and prev_rev > 10000:
            drop_amount = prev_rev - latest_rev
            results.append({
                "category": "PAYER_TREND",
                "severity": "CRITICAL" if rev_change < -0.60 else "HIGH",
                "title": f"{carrier} revenue dropped {abs(round(rev_change*100))}% ({prev} to {latest})",
                "description": f"{carrier}: ${prev_rev:,.0f} ({prev}) -> ${latest_rev:,.0f} ({latest}). Decline: ${drop_amount:,.0f}.",
                "recommendation": f"Investigate {carrier} volume drop.",
                "estimated_impact": round(drop_amount, 2), "affected_count": 0,
                "entity_type": "PAYER", "entity_id": carrier,
                "data": {"carrier": carrier, "rev_change_pct": round(rev_change * 100, 1)},
            })
    return results


def _analyze_physician_denial_rates() -> list[dict]:
    results = []
    rows = db.session.query(
        BillingRecord.referring_doctor.label("doctor"),
        func.count().label("total"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
        func.sum(BillingRecord.total_payment).label("revenue"),
    ).filter(not_written_off()).group_by(BillingRecord.referring_doctor).having(func.count() >= 20).all()

    global_r = db.session.query(
        func.count().label("total"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
    ).filter(not_written_off()).one()
    global_rate = global_r.denied / global_r.total if global_r.total else 0

    for r in rows:
        denial_rate = r.denied / r.total if r.total else 0
        if denial_rate > global_rate * 1.5 and r.denied >= 10:
            avg_rev = float(r.revenue or 0) / max(r.total - r.denied, 1)
            results.append({
                "category": "PHYSICIAN_ALERT",
                "severity": "HIGH" if denial_rate > 0.3 else "MEDIUM",
                "title": f"Dr. {r.doctor}: {round(denial_rate*100)}% denial rate (avg: {round(global_rate*100)}%)",
                "description": f"{r.denied} of {r.total} claims denied. {round(denial_rate/global_rate, 1)}x practice average.",
                "recommendation": f"Review coding patterns for Dr. {r.doctor}'s referrals.",
                "estimated_impact": round(r.denied * avg_rev, 2), "affected_count": r.denied,
                "entity_type": "PHYSICIAN", "entity_id": r.doctor,
                "data": {"doctor": r.doctor, "denial_rate": round(denial_rate * 100, 1)},
            })
    return results


def _analyze_filing_risks() -> list[dict]:
    results = []
    today = date.today()

    past_count = db.session.query(func.count()).filter(
        BillingRecord.total_payment == 0,
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline < today,
        not_written_off(),
    ).scalar() or 0

    warning_count = db.session.query(func.count()).filter(
        BillingRecord.total_payment == 0,
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline >= today,
        BillingRecord.appeal_deadline <= today + timedelta(days=30),
        not_written_off(),
    ).scalar() or 0

    if past_count > 0:
        results.append({
            "category": "FILING_RISK", "severity": "CRITICAL",
            "title": f"{past_count} claims past filing/appeal deadline — revenue lost",
            "description": f"{past_count} unpaid claims past deadline. This revenue is NOT recoverable — included as a loss metric, not a recovery opportunity.",
            "recommendation": "Review for lessons learned. Prevent future occurrences by improving timely filing workflows.",
            "estimated_impact": 0, "affected_count": past_count,
            "entity_type": None, "entity_id": None,
            "data": {"past_count": past_count},
        })

    if warning_count > 0:
        results.append({
            "category": "FILING_RISK", "severity": "HIGH",
            "title": f"{warning_count} claims approaching filing deadline (30 days)",
            "description": f"{warning_count} unpaid claims with deadlines in next 30 days.",
            "recommendation": "Prioritize for immediate action.",
            "estimated_impact": warning_count * 500, "affected_count": warning_count,
            "entity_type": None, "entity_id": None,
            "data": {"warning_count": warning_count},
        })
    return results


def _analyze_modality_pricing_gaps() -> list[dict]:
    results = []
    fee_map = {fs.modality: float(fs.expected_rate) for fs in FeeSchedule.query.filter_by(payer_code="DEFAULT").all()}

    rows = db.session.query(
        BillingRecord.modality.label("modality"),
        func.count().label("count"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
    ).filter(BillingRecord.total_payment > 0, not_written_off()).group_by(
        BillingRecord.modality
    ).having(func.count() >= 20).all()

    for r in rows:
        expected = fee_map.get(r.modality)
        if not expected:
            continue
        avg_pay = float(r.avg_payment or 0)
        ratio = avg_pay / expected
        if ratio < 0.60:
            gap = (expected - avg_pay) * r.count
            results.append({
                "category": "REVENUE_OPPORTUNITY", "severity": "HIGH",
                "title": f"{r.modality} reimbursement at {round(ratio*100)}% of fee schedule",
                "description": f"Avg ${avg_pay:,.0f} vs expected ${expected:,.0f} ({r.count} claims). Gap: ${gap:,.0f}.",
                "recommendation": f"Audit {r.modality} fee schedule and contracts.",
                "estimated_impact": round(gap, 2), "affected_count": r.count,
                "entity_type": "MODALITY", "entity_id": r.modality,
                "data": {"modality": r.modality, "ratio": round(ratio, 3)},
            })
    return results


def _analyze_process_improvements() -> list[dict]:
    results = []

    no_carrier = db.session.query(func.count()).filter(
        or_(BillingRecord.insurance_carrier.is_(None), BillingRecord.insurance_carrier == "")
    ).scalar() or 0
    if no_carrier > 50:
        results.append({
            "category": "PROCESS_IMPROVEMENT", "severity": "MEDIUM",
            "title": f"{no_carrier} claims with missing insurance carrier",
            "description": f"{no_carrier} claims have no carrier. Cannot be billed.",
            "recommendation": "Implement front-desk insurance verification.",
            "estimated_impact": no_carrier * 200, "affected_count": no_carrier,
            "entity_type": None, "entity_id": None,
            "data": {"unknown_carrier_count": no_carrier},
        })

    no_era = db.session.query(func.count()).filter(
        BillingRecord.era_claim_id.is_(None),
        BillingRecord.total_payment > 0,
        not_written_off(),
    ).scalar() or 0
    total_paid = db.session.query(func.count()).filter(
        BillingRecord.total_payment > 0, not_written_off()
    ).scalar() or 0

    if total_paid > 0 and no_era / total_paid > 0.3:
        results.append({
            "category": "PROCESS_IMPROVEMENT", "severity": "MEDIUM",
            "title": f"{round(no_era/total_paid*100)}% of paid claims not linked to ERA",
            "description": f"{no_era} of {total_paid} paid claims have no ERA linked.",
            "recommendation": "Import more 835 files and run auto-matcher.",
            "estimated_impact": 0, "affected_count": no_era,
            "entity_type": None, "entity_id": None,
            "data": {"unlinked_count": no_era},
        })

    return results


def persist_recommendations(recommendations: list[dict]) -> int:
    """Save recommendations to insight_log table, deduplicating by title."""
    existing = {r[0] for r in db.session.query(InsightLog.title).filter(
        InsightLog.status.in_(["OPEN", "IN_PROGRESS"])
    ).all()}

    count = 0
    for rec in recommendations:
        if rec["title"] in existing:
            continue
        log = InsightLog(
            category=rec["category"], severity=rec["severity"],
            title=rec["title"], description=rec["description"],
            recommendation=rec["recommendation"],
            estimated_impact=rec.get("estimated_impact"),
            affected_count=rec.get("affected_count"),
            entity_type=rec.get("entity_type"),
            entity_id=rec.get("entity_id"),
            data=rec.get("data"),
            status="OPEN",
        )
        db.session.add(log)
        count += 1

    if count:
        db.session.commit()
    return count
