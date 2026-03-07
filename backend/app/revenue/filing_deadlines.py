"""
Timely Filing Deadline Tracker (F-06).

Computes appeal_deadline = service_date + payers.filing_deadline_days.
Flags claims where total_payment=0 and deadline is approaching or past.
Categories: PAST_DEADLINE, WARNING_30DAY, SAFE.
Implements BR-05.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.payer import Payer

logger = logging.getLogger(__name__)

WARNING_DAYS = 30  # Days before deadline to trigger warning


async def get_filing_deadlines(
    session: AsyncSession,
    status_filter: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    """
    Get filing deadline status for all unpaid claims.

    status_filter: PAST_DEADLINE, WARNING_30DAY, SAFE
    """
    today = date.today()

    # Load payer filing deadlines
    payer_result = await session.execute(select(Payer))
    payers = {p.code: p.filing_deadline_days for p in payer_result.scalars().all()}

    # Get unpaid claims
    query = select(BillingRecord).where(BillingRecord.total_payment == 0)
    result = await session.execute(query)
    records = result.scalars().all()

    items = []
    for rec in records:
        deadline_days = payers.get(rec.insurance_carrier, 180)
        deadline = rec.service_date + timedelta(days=deadline_days)
        days_remaining = (deadline - today).days

        if days_remaining < 0:
            status = "PAST_DEADLINE"
        elif days_remaining <= WARNING_DAYS:
            status = "WARNING_30DAY"
        else:
            status = "SAFE"

        if status_filter and status != status_filter:
            continue

        items.append({
            "id": rec.id,
            "patient_name": rec.patient_name,
            "service_date": rec.service_date.isoformat(),
            "insurance_carrier": rec.insurance_carrier,
            "modality": rec.modality,
            "scan_type": rec.scan_type,
            "filing_deadline": deadline.isoformat(),
            "days_remaining": days_remaining,
            "status": status,
            "referring_doctor": rec.referring_doctor,
        })

    # Sort by days_remaining ascending (most urgent first)
    items.sort(key=lambda x: x["days_remaining"])

    total = len(items)
    paginated = items[(page - 1) * per_page: page * per_page]

    return {
        "items": paginated,
        "total": total,
        "page": page,
        "per_page": per_page,
    }


async def get_filing_deadline_alerts(session: AsyncSession) -> dict:
    """
    Get only active alerts (PAST_DEADLINE and WARNING_30DAY claims).
    """
    today = date.today()

    payer_result = await session.execute(select(Payer))
    payers = {p.code: p.filing_deadline_days for p in payer_result.scalars().all()}

    result = await session.execute(
        select(BillingRecord).where(BillingRecord.total_payment == 0)
    )
    records = result.scalars().all()

    past_deadline = []
    warning = []

    for rec in records:
        deadline_days = payers.get(rec.insurance_carrier, 180)
        deadline = rec.service_date + timedelta(days=deadline_days)
        days_remaining = (deadline - today).days

        item = {
            "id": rec.id,
            "patient_name": rec.patient_name,
            "service_date": rec.service_date.isoformat(),
            "insurance_carrier": rec.insurance_carrier,
            "modality": rec.modality,
            "filing_deadline": deadline.isoformat(),
            "days_remaining": days_remaining,
        }

        if days_remaining < 0:
            past_deadline.append(item)
        elif days_remaining <= WARNING_DAYS:
            warning.append(item)

    past_deadline.sort(key=lambda x: x["days_remaining"])
    warning.sort(key=lambda x: x["days_remaining"])

    return {
        "past_deadline_count": len(past_deadline),
        "warning_count": len(warning),
        "past_deadline": past_deadline,
        "warning": warning,
    }


async def update_appeal_deadlines(session: AsyncSession) -> int:
    """
    Batch-update appeal_deadline on billing_records based on payer filing limits.
    Called after import. Returns count updated.
    """
    payer_result = await session.execute(select(Payer))
    payers = {p.code: p.filing_deadline_days for p in payer_result.scalars().all()}

    result = await session.execute(
        select(BillingRecord).where(BillingRecord.appeal_deadline.is_(None))
    )
    records = result.scalars().all()

    count = 0
    for rec in records:
        deadline_days = payers.get(rec.insurance_carrier, 180)
        rec.appeal_deadline = rec.service_date + timedelta(days=deadline_days)
        count += 1

    if count:
        await session.commit()

    return count
