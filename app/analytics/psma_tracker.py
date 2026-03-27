"""PSMA PET Tracking Analytics (F-13).

Tracks PSMA-specific PET scans: volume, revenue, avg reimbursement,
YoY trend, comparison vs standard PET.
"""

from sqlalchemy import func, extract

from app.models import db, BillingRecord


def get_psma_summary():
    """Get PSMA PET overview stats."""
    psma_records = BillingRecord.query.filter_by(is_psma=True)
    standard_pet = BillingRecord.query.filter(
        BillingRecord.modality == "PET",
        BillingRecord.is_psma == False  # noqa: E712
    )

    psma_count = psma_records.count()
    psma_revenue = db.session.query(func.sum(BillingRecord.total_payment)).filter(
        BillingRecord.is_psma == True  # noqa: E712
    ).scalar() or 0
    psma_avg = (psma_revenue / psma_count) if psma_count > 0 else 0

    std_count = standard_pet.count()
    std_revenue = db.session.query(func.sum(BillingRecord.total_payment)).filter(
        BillingRecord.modality == "PET",
        BillingRecord.is_psma == False  # noqa: E712
    ).scalar() or 0
    std_avg = (std_revenue / std_count) if std_count > 0 else 0

    return {
        "psma": {
            "count": psma_count,
            "revenue": round(psma_revenue, 2),
            "avg_reimbursement": round(psma_avg, 2),
        },
        "standard_pet": {
            "count": std_count,
            "revenue": round(std_revenue, 2),
            "avg_reimbursement": round(std_avg, 2),
        },
        "premium_per_scan": round(psma_avg - std_avg, 2),
    }


def get_psma_by_year():
    """PSMA volume and revenue by year."""
    results = db.session.query(
        func.strftime("%Y", BillingRecord.service_date).label("year"),
        func.count(BillingRecord.id).label("count"),
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
    ).filter(
        BillingRecord.is_psma == True  # noqa: E712
    ).group_by(
        func.strftime("%Y", BillingRecord.service_date)
    ).order_by("year").all()

    return [{
        "year": r.year,
        "count": r.count,
        "revenue": round(r.revenue, 2),
        "avg_payment": round(r.avg_payment, 2),
    } for r in results]


def get_psma_by_physician():
    """PSMA referral patterns by physician."""
    results = db.session.query(
        BillingRecord.referring_doctor,
        func.count(BillingRecord.id).label("count"),
        func.sum(BillingRecord.total_payment).label("revenue"),
    ).filter(
        BillingRecord.is_psma == True  # noqa: E712
    ).group_by(BillingRecord.referring_doctor).order_by(
        func.count(BillingRecord.id).desc()
    ).limit(20).all()

    return [{
        "physician": r.referring_doctor,
        "count": r.count,
        "revenue": round(r.revenue, 2),
    } for r in results]


def get_psma_by_carrier():
    """PSMA reimbursement by insurance carrier."""
    results = db.session.query(
        BillingRecord.insurance_carrier,
        func.count(BillingRecord.id).label("count"),
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
    ).filter(
        BillingRecord.is_psma == True  # noqa: E712
    ).group_by(BillingRecord.insurance_carrier).order_by(
        func.sum(BillingRecord.total_payment).desc()
    ).all()

    return [{
        "carrier": r.insurance_carrier,
        "count": r.count,
        "revenue": round(r.revenue, 2),
        "avg_payment": round(r.avg_payment, 2),
    } for r in results]
