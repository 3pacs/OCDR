"""
Reports endpoints — revenue, AR aging, denial rates, collection rates, trends.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.appointment import Appointment
from app.models.claim import Claim
from app.models.learning import DenialPattern
from app.models.payment import Payment
from app.models.user import User

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get(
    "/dashboard-summary",
    summary="Dashboard home — today's schedule, pending EOBs, unmatched payments, revenue",
)
async def get_dashboard_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reports:read")),
):
    today = date.today()
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)

    # Today's appointments
    appts_today = (
        await db.execute(
            select(func.count())
            .select_from(Appointment)
            .where(Appointment.scan_date == today)
        )
    ).scalar_one()

    # Pending EOBs (needs_review)
    from app.models.eob import EOB
    eobs_pending = (
        await db.execute(
            select(func.count())
            .select_from(EOB)
            .where(EOB.processed_status == "needs_review")
        )
    ).scalar_one()

    # Unmatched payments
    unmatched_payments = (
        await db.execute(
            select(func.count())
            .select_from(Payment)
            .where(Payment.posting_status == "needs_review")
        )
    ).scalar_one()

    # Revenue sums
    def revenue_sum_query(start: date):
        return (
            select(func.coalesce(func.sum(Payment.amount), 0))
            .where(
                and_(
                    Payment.payment_date >= start,
                    Payment.payment_date <= today,
                    Payment.posting_status == "posted",
                )
            )
        )

    revenue_today = float((await db.execute(revenue_sum_query(today))).scalar_one())
    revenue_week = float((await db.execute(revenue_sum_query(week_start))).scalar_one())
    revenue_month = float((await db.execute(revenue_sum_query(month_start))).scalar_one())

    # Denied claims count
    denied_claims = (
        await db.execute(
            select(func.count())
            .select_from(Claim)
            .where(Claim.claim_status == "denied")
        )
    ).scalar_one()

    return {
        "today": today.isoformat(),
        "appointments_today": appts_today,
        "eobs_pending_review": eobs_pending,
        "unmatched_payments": unmatched_payments,
        "denied_claims": denied_claims,
        "revenue": {
            "today": revenue_today,
            "week_to_date": revenue_week,
            "month_to_date": revenue_month,
        },
    }


@router.get(
    "/revenue-by-modality",
    summary="Revenue breakdown by imaging modality",
)
async def revenue_by_modality(
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reports:read")),
):
    from app.models.scan import Scan

    q = (
        select(
            Appointment.modality,
            func.coalesce(func.sum(Payment.amount), 0).label("total_paid"),
            func.count(Payment.id).label("payment_count"),
        )
        .select_from(Payment)
        .join(Claim, Payment.claim_id == Claim.id, isouter=True)
        .join(Scan, Claim.scan_id == Scan.id, isouter=True)
        .join(Appointment, Scan.appointment_id == Appointment.id, isouter=True)
        .where(Payment.posting_status == "posted")
        .group_by(Appointment.modality)
    )

    if date_from:
        q = q.where(Payment.payment_date >= date_from)
    if date_to:
        q = q.where(Payment.payment_date <= date_to)

    result = await db.execute(q)
    rows = result.all()
    return [
        {"modality": r.modality or "Unknown", "total_paid": float(r.total_paid), "count": r.payment_count}
        for r in rows
    ]


@router.get(
    "/denial-rates",
    summary="Denial rates by payer and CPT code",
)
async def denial_rates(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reports:read")),
):
    result = await db.execute(
        select(DenialPattern)
        .order_by(DenialPattern.occurrence_count.desc())
        .limit(50)
    )
    patterns = result.scalars().all()
    return [
        {
            "payer_name": p.payer_name,
            "cpt_code": p.cpt_code,
            "denial_code": p.denial_code,
            "denial_reason": p.denial_reason,
            "occurrence_count": p.occurrence_count,
            "total_denied_amount": p.total_denied_amount,
            "last_seen_at": p.last_seen_at.isoformat() if p.last_seen_at else None,
        }
        for p in patterns
    ]


@router.get(
    "/collection-rate-by-payer",
    summary="Collection rate per payer (paid / billed)",
)
async def collection_rate_by_payer(
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reports:read")),
):
    from app.models.insurance import Insurance

    q = (
        select(
            Insurance.payer_name,
            func.coalesce(func.sum(Claim.billed_amount), 0).label("total_billed"),
            func.coalesce(func.sum(Claim.paid_amount), 0).label("total_paid"),
            func.count(Claim.id).label("claim_count"),
        )
        .select_from(Claim)
        .join(Insurance, Claim.insurance_id == Insurance.id, isouter=True)
        .where(Claim.claim_status.in_(["paid", "partial"]))
        .group_by(Insurance.payer_name)
    )

    if date_from:
        q = q.where(Claim.date_of_service >= date_from)
    if date_to:
        q = q.where(Claim.date_of_service <= date_to)

    result = await db.execute(q)
    rows = result.all()
    return [
        {
            "payer_name": r.payer_name or "Unknown",
            "total_billed": float(r.total_billed),
            "total_paid": float(r.total_paid),
            "collection_rate_pct": round(float(r.total_paid) / float(r.total_billed) * 100, 1)
            if r.total_billed
            else 0.0,
            "claim_count": r.claim_count,
        }
        for r in rows
    ]


@router.get(
    "/ar-aging",
    summary="Full AR aging report by payer",
)
async def ar_aging_by_payer(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reports:read")),
):
    from app.models.insurance import Insurance

    today = date.today()
    open_statuses = ("submitted", "accepted", "pending", "partial", "denied")

    result = await db.execute(
        select(Claim, Insurance.payer_name)
        .join(Insurance, Claim.insurance_id == Insurance.id, isouter=True)
        .where(Claim.claim_status.in_(open_statuses))
    )
    rows = result.all()

    payer_buckets: Dict[str, Dict[str, float]] = {}
    for claim, payer_name in rows:
        pn = payer_name or "Unknown"
        if pn not in payer_buckets:
            payer_buckets[pn] = {"0_30": 0, "31_60": 0, "61_90": 0, "91_120": 0, "120_plus": 0, "total": 0}
        if not claim.date_submitted or not claim.billed_amount:
            continue
        days = (today - claim.date_submitted).days
        amt = float(claim.billed_amount)
        payer_buckets[pn]["total"] += amt
        if days <= 30:
            payer_buckets[pn]["0_30"] += amt
        elif days <= 60:
            payer_buckets[pn]["31_60"] += amt
        elif days <= 90:
            payer_buckets[pn]["61_90"] += amt
        elif days <= 120:
            payer_buckets[pn]["91_120"] += amt
        else:
            payer_buckets[pn]["120_plus"] += amt

    return [{"payer_name": k, **v} for k, v in sorted(payer_buckets.items())]
