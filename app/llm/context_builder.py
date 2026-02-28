"""Builds context for LLM prompts by summarizing recent data.

Provides a snapshot of the current data state so the LLM can give
contextually relevant answers without needing to query everything.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func as sa_func

from app.models import db, BillingRecord, EraPayment


def build_context() -> dict:
    """Return a summary of recent data state for LLM prompt context.

    Returns::

        {
            "total_billing_records": int,
            "total_revenue": float,
            "date_range": {"earliest": str, "latest": str},
            "top_carriers": [{"carrier": str, "count": int, "revenue": float}, ...],
            "top_modalities": [{"modality": str, "count": int, "revenue": float}, ...],
            "recent_imports": int,
            "pending_denials": int,
        }
    """
    try:
        return _build_context_impl()
    except Exception:
        # Return safe defaults if database is not available
        return {
            "total_billing_records": 0,
            "total_revenue": 0.0,
            "date_range": {"earliest": None, "latest": None},
            "top_carriers": [],
            "top_modalities": [],
            "recent_imports": 0,
            "pending_denials": 0,
        }


def _build_context_impl() -> dict:
    """Internal implementation that may raise on DB errors."""

    # Total records and revenue
    totals = db.session.query(
        sa_func.count(BillingRecord.id),
        sa_func.coalesce(sa_func.sum(BillingRecord.total_payment), 0.0),
    ).first()
    total_records = totals[0] or 0
    total_revenue = round(totals[1] or 0.0, 2)

    # Date range
    date_range_row = db.session.query(
        sa_func.min(BillingRecord.service_date),
        sa_func.max(BillingRecord.service_date),
    ).first()
    earliest = (date_range_row[0].isoformat()
                if date_range_row and date_range_row[0] else None)
    latest = (date_range_row[1].isoformat()
              if date_range_row and date_range_row[1] else None)

    # Top carriers (top 10 by count)
    carrier_rows = (
        db.session.query(
            BillingRecord.insurance_carrier,
            sa_func.count(BillingRecord.id).label("cnt"),
            sa_func.coalesce(
                sa_func.sum(BillingRecord.total_payment), 0.0
            ).label("rev"),
        )
        .group_by(BillingRecord.insurance_carrier)
        .order_by(sa_func.count(BillingRecord.id).desc())
        .limit(10)
        .all()
    )
    top_carriers = [
        {
            "carrier": row[0],
            "count": row[1],
            "revenue": round(row[2] or 0.0, 2),
        }
        for row in carrier_rows
    ]

    # Top modalities (top 10 by count)
    modality_rows = (
        db.session.query(
            BillingRecord.modality,
            sa_func.count(BillingRecord.id).label("cnt"),
            sa_func.coalesce(
                sa_func.sum(BillingRecord.total_payment), 0.0
            ).label("rev"),
        )
        .group_by(BillingRecord.modality)
        .order_by(sa_func.count(BillingRecord.id).desc())
        .limit(10)
        .all()
    )
    top_modalities = [
        {
            "modality": row[0],
            "count": row[1],
            "revenue": round(row[2] or 0.0, 2),
        }
        for row in modality_rows
    ]

    # Recent imports (last 7 days)
    seven_days_ago = datetime.now(timezone.utc) - timedelta(days=7)
    recent_imports = (
        db.session.query(sa_func.count(BillingRecord.id))
        .filter(BillingRecord.created_at >= seven_days_ago)
        .scalar()
    ) or 0

    # Pending denials (denial_status = 'DENIED')
    pending_denials = (
        db.session.query(sa_func.count(BillingRecord.id))
        .filter(BillingRecord.denial_status == "DENIED")
        .scalar()
    ) or 0

    return {
        "total_billing_records": total_records,
        "total_revenue": total_revenue,
        "date_range": {"earliest": earliest, "latest": latest},
        "top_carriers": top_carriers,
        "top_modalities": top_modalities,
        "recent_imports": recent_imports,
        "pending_denials": pending_denials,
    }
