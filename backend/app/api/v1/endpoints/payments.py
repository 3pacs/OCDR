"""
Payment CRUD endpoints — manual posting and status management.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.payment import Payment
from app.models.user import User
from app.schemas.payment import PaymentCreate, PaymentRead, PaymentUpdate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/payments", tags=["Payments"])


@router.post(
    "/",
    response_model=PaymentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Record a new payment",
)
async def create_payment(
    body: PaymentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("payments:write")),
):
    payment = Payment(**body.model_dump())
    db.add(payment)
    await db.flush()
    await db.refresh(payment)
    return payment


@router.get(
    "/",
    response_model=PaginatedResponse[PaymentRead],
    summary="List payments with filters",
)
async def list_payments(
    patient_id: Optional[int] = None,
    claim_id: Optional[int] = None,
    posting_status: Optional[str] = None,
    payment_type: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("payments:read")),
):
    q = select(Payment)
    filters = []
    if patient_id:
        filters.append(Payment.patient_id == patient_id)
    if claim_id:
        filters.append(Payment.claim_id == claim_id)
    if posting_status:
        filters.append(Payment.posting_status == posting_status)
    if payment_type:
        filters.append(Payment.payment_type == payment_type)
    if filters:
        q = q.where(and_(*filters))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(
        q.order_by(Payment.payment_date.desc()).offset(offset).limit(page_size)
    )
    items = result.scalars().all()

    return PaginatedResponse(
        items=[PaymentRead.model_validate(p) for p in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/needs-review",
    response_model=list[PaymentRead],
    summary="Get payments queued for manual review",
)
async def get_payments_needing_review(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("payments:read")),
):
    result = await db.execute(
        select(Payment)
        .where(Payment.posting_status == "needs_review")
        .order_by(Payment.created_at.asc())
    )
    return result.scalars().all()


@router.get(
    "/{payment_id}",
    response_model=PaymentRead,
    summary="Get a payment by ID",
)
async def get_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("payments:read")),
):
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    return payment


@router.patch(
    "/{payment_id}",
    response_model=PaymentRead,
    summary="Update a payment",
)
async def update_payment(
    payment_id: int,
    body: PaymentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("payments:write")),
):
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    update_data = body.model_dump(exclude_unset=True)

    # If being posted, set posted_by and posted_date automatically
    if update_data.get("posting_status") == "posted" and not payment.posted_by:
        update_data["posted_by"] = current_user.username
        update_data["posted_date"] = datetime.now(timezone.utc)

    for field, value in update_data.items():
        setattr(payment, field, value)

    await db.flush()
    await db.refresh(payment)
    return payment


@router.post(
    "/{payment_id}/post",
    response_model=PaymentRead,
    summary="Manually post a payment",
)
async def post_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("payments:write")),
):
    """Marks a payment as 'posted' with current user and timestamp."""
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")

    payment.posting_status = "posted"
    payment.posted_by = current_user.username
    payment.posted_date = datetime.now(timezone.utc)

    await db.flush()
    await db.refresh(payment)
    return payment


@router.delete(
    "/{payment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a payment",
)
async def delete_payment(
    payment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("payments:write")),
):
    result = await db.execute(select(Payment).where(Payment.id == payment_id))
    payment = result.scalar_one_or_none()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment not found")
    await db.delete(payment)
