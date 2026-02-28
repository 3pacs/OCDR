"""Gado Contrast Cost Tracking (F-14).

Dashboard: total gado claims, revenue, by physician, by year.
Cost analysis with configurable $/dose.
Margin calc: revenue per $1 gado cost.
"""

from sqlalchemy import func

from app.models import db, BillingRecord


DEFAULT_GADO_COST_PER_DOSE = 50.0


def get_gado_summary(cost_per_dose=None):
    """Get gadolinium contrast usage overview."""
    if cost_per_dose is None:
        cost_per_dose = DEFAULT_GADO_COST_PER_DOSE

    gado_count = BillingRecord.query.filter_by(gado_used=True).count()
    gado_revenue = db.session.query(func.sum(BillingRecord.total_payment)).filter(
        BillingRecord.gado_used == True  # noqa: E712
    ).scalar() or 0

    total_gado_cost = gado_count * cost_per_dose
    margin = (gado_revenue / total_gado_cost) if total_gado_cost > 0 else 0

    # By modality
    by_modality = db.session.query(
        BillingRecord.modality,
        func.count(BillingRecord.id).label("count"),
        func.sum(BillingRecord.total_payment).label("revenue"),
    ).filter(
        BillingRecord.gado_used == True  # noqa: E712
    ).group_by(BillingRecord.modality).all()

    return {
        "total_gado_claims": gado_count,
        "total_revenue": round(gado_revenue, 2),
        "cost_per_dose": cost_per_dose,
        "total_gado_cost": round(total_gado_cost, 2),
        "margin_ratio": round(margin, 2),
        "revenue_per_dollar": round(margin, 2),
        "by_modality": [{
            "modality": r.modality,
            "count": r.count,
            "revenue": round(r.revenue, 2),
        } for r in by_modality],
    }


def get_gado_by_year(cost_per_dose=None):
    """Gado usage by year."""
    if cost_per_dose is None:
        cost_per_dose = DEFAULT_GADO_COST_PER_DOSE

    results = db.session.query(
        func.strftime("%Y", BillingRecord.service_date).label("year"),
        func.count(BillingRecord.id).label("count"),
        func.sum(BillingRecord.total_payment).label("revenue"),
    ).filter(
        BillingRecord.gado_used == True  # noqa: E712
    ).group_by(
        func.strftime("%Y", BillingRecord.service_date)
    ).order_by("year").all()

    return [{
        "year": r.year,
        "count": r.count,
        "revenue": round(r.revenue, 2),
        "gado_cost": round(r.count * cost_per_dose, 2),
        "margin": round(r.revenue / (r.count * cost_per_dose), 2) if r.count > 0 else 0,
    } for r in results]


def get_gado_by_physician():
    """Gado usage by referring physician."""
    results = db.session.query(
        BillingRecord.referring_doctor,
        func.count(BillingRecord.id).label("count"),
        func.sum(BillingRecord.total_payment).label("revenue"),
    ).filter(
        BillingRecord.gado_used == True  # noqa: E712
    ).group_by(BillingRecord.referring_doctor).order_by(
        func.count(BillingRecord.id).desc()
    ).limit(20).all()

    return [{
        "physician": r.referring_doctor,
        "count": r.count,
        "revenue": round(r.revenue, 2),
    } for r in results]


def get_gado_margin_analysis(cost_per_dose=None):
    """Detailed margin analysis by carrier."""
    if cost_per_dose is None:
        cost_per_dose = DEFAULT_GADO_COST_PER_DOSE

    results = db.session.query(
        BillingRecord.insurance_carrier,
        func.count(BillingRecord.id).label("count"),
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
    ).filter(
        BillingRecord.gado_used == True  # noqa: E712
    ).group_by(BillingRecord.insurance_carrier).order_by(
        func.sum(BillingRecord.total_payment).desc()
    ).all()

    return [{
        "carrier": r.insurance_carrier,
        "count": r.count,
        "revenue": round(r.revenue, 2),
        "avg_payment": round(r.avg_payment, 2),
        "gado_cost": round(r.count * cost_per_dose, 2),
        "net_margin": round(r.revenue - (r.count * cost_per_dose), 2),
    } for r in results]
