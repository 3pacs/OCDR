"""API routes for ERA payments (F-02)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.db.session import get_db
from backend.app.models.era import ERAPayment, ERAClaimLine

router = APIRouter()


@router.get("/payments")
async def list_payments(
    payer: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List ERA payments (F-02)."""
    query = select(ERAPayment)
    if payer:
        query = query.where(ERAPayment.payer_name.ilike(f"%{payer}%"))
    if date_from:
        query = query.where(ERAPayment.payment_date >= date_from)
    if date_to:
        query = query.where(ERAPayment.payment_date <= date_to)
    query = query.order_by(ERAPayment.payment_date.desc())

    # Count
    count_q = select(func.count()).select_from(query.subquery())
    total = (await db.execute(count_q)).scalar()

    # Paginate
    query = query.offset((page - 1) * per_page).limit(per_page)
    result = await db.execute(query)
    payments = result.scalars().all()

    return {
        "items": [
            {
                "id": p.id,
                "filename": p.filename,
                "check_eft_number": p.check_eft_number,
                "payment_amount": float(p.payment_amount) if p.payment_amount else None,
                "payment_date": p.payment_date.isoformat() if p.payment_date else None,
                "payment_method": p.payment_method,
                "payer_name": p.payer_name,
                "parsed_at": p.parsed_at.isoformat() if p.parsed_at else None,
            }
            for p in payments
        ],
        "total": total,
        "page": page,
        "per_page": per_page,
    }


@router.get("/claims/{claim_id}")
async def get_claim(claim_id: int, db: AsyncSession = Depends(get_db)):
    """Get ERA claim detail (F-02)."""
    result = await db.execute(
        select(ERAClaimLine).where(ERAClaimLine.id == claim_id)
    )
    claim = result.scalar_one_or_none()
    if not claim:
        from fastapi import HTTPException
        raise HTTPException(404, "Claim not found")

    return {
        "id": claim.id,
        "era_payment_id": claim.era_payment_id,
        "claim_id": claim.claim_id,
        "claim_status": claim.claim_status,
        "billed_amount": float(claim.billed_amount) if claim.billed_amount else None,
        "paid_amount": float(claim.paid_amount) if claim.paid_amount else None,
        "patient_name_835": claim.patient_name_835,
        "service_date_835": claim.service_date_835.isoformat() if claim.service_date_835 else None,
        "cpt_code": claim.cpt_code,
        "cas_group_code": claim.cas_group_code,
        "cas_reason_code": claim.cas_reason_code,
        "cas_adjustment_amount": float(claim.cas_adjustment_amount) if claim.cas_adjustment_amount else None,
        "match_confidence": float(claim.match_confidence) if claim.match_confidence else None,
        "matched_billing_id": claim.matched_billing_id,
    }
