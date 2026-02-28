"""
Claims aging analysis module.

Generates aging reports with 30/60/90/120+ day buckets using SQL aggregate
queries and CASE expressions for efficient bucket classification. Does NOT
load all records into memory.
"""

from datetime import date
from sqlalchemy import func, case, literal_column
from app.models import db, BillingRecord


# Bucket definitions: (label, min_days_inclusive, max_days_inclusive_or_None)
_BUCKET_DEFS = [
    ("0-30", 0, 30),
    ("31-60", 31, 60),
    ("61-90", 61, 90),
    ("91-120", 91, 120),
    ("121+", 121, None),
]


def _age_days_expr():
    """Build a SQLite-compatible expression for days since service_date.

    Uses julianday('now') - julianday(service_date) for SQLite.
    Returns a SQLAlchemy column expression.
    """
    return func.julianday(func.date("now")) - func.julianday(BillingRecord.service_date)


def _bucket_case_expr():
    """Build a SQL CASE expression that classifies a record into an aging bucket.

    Returns a SQLAlchemy case() expression yielding the bucket label string.
    """
    age = _age_days_expr()
    return case(
        (age <= 30, literal_column("'0-30'")),
        (age <= 60, literal_column("'31-60'")),
        (age <= 90, literal_column("'61-90'")),
        (age <= 120, literal_column("'91-120'")),
        else_=literal_column("'121+'"),
    ).label("bucket")


def _base_query_filter(query, carrier=None):
    """Apply common filters to aging queries.

    Filters to records that have an outstanding balance (denial or unpaid).
    Optionally filters by carrier.
    """
    # Include records with denial status or zero/null payment
    query = query.filter(
        db.or_(
            BillingRecord.denial_status.isnot(None),
            BillingRecord.total_payment == 0,
            BillingRecord.total_payment.is_(None),
        )
    )
    if carrier:
        query = query.filter(BillingRecord.insurance_carrier == carrier)
    return query


def get_aging_report(carrier=None) -> dict:
    """Generate aging report with 30/60/90/120+ day buckets.

    Uses SQL CASE expressions for bucket classification and aggregate queries
    for efficient computation. Does NOT load all records into memory.

    Args:
        carrier: Optional carrier name to filter by. If None, includes all.

    Returns:
        {
            "buckets": [
                {"range": "0-30", "count": int, "total_amount": float},
                {"range": "31-60", "count": int, "total_amount": float},
                {"range": "61-90", "count": int, "total_amount": float},
                {"range": "91-120", "count": int, "total_amount": float},
                {"range": "121+", "count": int, "total_amount": float},
            ],
            "by_carrier": {
                "CarrierName": [same bucket structure],
                ...
            },
            "summary": {
                "total_outstanding": float,
                "total_claims": int,
                "avg_age_days": float,
            }
        }
    """
    bucket_expr = _bucket_case_expr()
    age_expr = _age_days_expr()

    # ── Overall bucket aggregates ──────────────────────────────────
    bucket_query = db.session.query(
        bucket_expr,
        func.count(BillingRecord.id).label("cnt"),
        func.coalesce(func.sum(BillingRecord.total_payment), 0.0).label("total_amt"),
    ).group_by(literal_column("bucket"))

    bucket_query = _base_query_filter(bucket_query, carrier)
    bucket_rows = bucket_query.all()

    # Build a dict keyed by bucket label for easy lookup
    bucket_map = {}
    for row in bucket_rows:
        bucket_map[row[0]] = {
            "range": row[0],
            "count": int(row[1]),
            "total_amount": round(float(row[2]), 2),
        }

    # Ensure all buckets exist in output, even if empty
    buckets = []
    for label, _, _ in _BUCKET_DEFS:
        if label in bucket_map:
            buckets.append(bucket_map[label])
        else:
            buckets.append({"range": label, "count": 0, "total_amount": 0.0})

    # ── Summary aggregates ─────────────────────────────────────────
    summary_query = db.session.query(
        func.count(BillingRecord.id).label("total_claims"),
        func.coalesce(func.sum(BillingRecord.total_payment), 0.0).label("total_outstanding"),
        func.coalesce(func.avg(age_expr), 0.0).label("avg_age"),
    )
    summary_query = _base_query_filter(summary_query, carrier)
    summary_row = summary_query.one()

    summary = {
        "total_outstanding": round(float(summary_row.total_outstanding), 2),
        "total_claims": int(summary_row.total_claims),
        "avg_age_days": round(float(summary_row.avg_age), 1),
    }

    # ── Per-carrier breakdown ──────────────────────────────────────
    by_carrier = {}

    if not carrier:
        carrier_bucket_query = db.session.query(
            BillingRecord.insurance_carrier,
            bucket_expr,
            func.count(BillingRecord.id).label("cnt"),
            func.coalesce(func.sum(BillingRecord.total_payment), 0.0).label("total_amt"),
        ).group_by(
            BillingRecord.insurance_carrier,
            literal_column("bucket"),
        )
        carrier_bucket_query = _base_query_filter(carrier_bucket_query)
        carrier_rows = carrier_bucket_query.all()

        # Organize into nested structure
        carrier_data = {}
        for row in carrier_rows:
            c_name = row[0] or "UNKNOWN"
            if c_name not in carrier_data:
                carrier_data[c_name] = {}
            carrier_data[c_name][row[1]] = {
                "range": row[1],
                "count": int(row[2]),
                "total_amount": round(float(row[3]), 2),
            }

        # Ensure all buckets for each carrier
        for c_name, c_buckets in carrier_data.items():
            carrier_list = []
            for label, _, _ in _BUCKET_DEFS:
                if label in c_buckets:
                    carrier_list.append(c_buckets[label])
                else:
                    carrier_list.append({"range": label, "count": 0, "total_amount": 0.0})
            by_carrier[c_name] = carrier_list
    else:
        # Single carrier requested; by_carrier contains just that one
        by_carrier[carrier] = buckets

    return {
        "buckets": buckets,
        "by_carrier": by_carrier,
        "summary": summary,
    }
