"""
Reconciliation CRUD endpoints.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.reconciliation import Reconciliation
from app.models.user import User
from app.schemas.reconciliation import (
    ReconciliationCreate,
    ReconciliationRead,
    ReconciliationUpdate,
)
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/reconciliation", tags=["Reconciliation"])


@router.post(
    "/",
    response_model=ReconciliationRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a reconciliation record for a claim",
)
async def create_reconciliation(
    body: ReconciliationCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reconciliation:write")),
):
    # Calculate variance
    data = body.model_dump()
    exp = data.get("expected_payment") or 0.0
    act = data.get("actual_payment") or 0.0
    variance = round(exp - act, 2)
    variance_pct = round((variance / exp * 100), 2) if exp else None

    data["variance"] = variance
    data["variance_pct"] = variance_pct
    # Auto-flag if |variance| > $10 or > 5%
    data["flagged_for_review"] = abs(variance) > 10 or (variance_pct is not None and abs(variance_pct) > 5)

    recon = Reconciliation(**data)
    db.add(recon)
    await db.flush()
    await db.refresh(recon)
    return recon


@router.get(
    "/",
    response_model=PaginatedResponse[ReconciliationRead],
    summary="List reconciliation records",
)
async def list_reconciliation(
    reconciliation_status: Optional[str] = None,
    flagged_only: bool = False,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reconciliation:read")),
):
    q = select(Reconciliation)
    filters = []
    if reconciliation_status:
        filters.append(Reconciliation.reconciliation_status == reconciliation_status)
    if flagged_only:
        filters.append(Reconciliation.flagged_for_review.is_(True))
    if filters:
        q = q.where(and_(*filters))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(
        q.order_by(Reconciliation.created_at.desc()).offset(offset).limit(page_size)
    )
    items = result.scalars().all()

    return PaginatedResponse(
        items=[ReconciliationRead.model_validate(r) for r in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/{recon_id}",
    response_model=ReconciliationRead,
    summary="Get a reconciliation record",
)
async def get_reconciliation(
    recon_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reconciliation:read")),
):
    result = await db.execute(select(Reconciliation).where(Reconciliation.id == recon_id))
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation record not found")
    return recon


@router.get(
    "/claim/{claim_id}",
    response_model=ReconciliationRead,
    summary="Get reconciliation for a specific claim",
)
async def get_reconciliation_by_claim(
    claim_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reconciliation:read")),
):
    result = await db.execute(
        select(Reconciliation).where(Reconciliation.claim_id == claim_id)
    )
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No reconciliation for this claim")
    return recon


@router.patch(
    "/{recon_id}",
    response_model=ReconciliationRead,
    summary="Update a reconciliation record",
)
async def update_reconciliation(
    recon_id: int,
    body: ReconciliationUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("reconciliation:write")),
):
    result = await db.execute(select(Reconciliation).where(Reconciliation.id == recon_id))
    recon = result.scalar_one_or_none()
    if not recon:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Reconciliation record not found")

    update_data = body.model_dump(exclude_unset=True)

    # Recalculate variance if amounts changed
    exp = update_data.get("expected_payment", recon.expected_payment) or 0.0
    act = update_data.get("actual_payment", recon.actual_payment) or 0.0
    if "expected_payment" in update_data or "actual_payment" in update_data:
        update_data["variance"] = round(exp - act, 2)
        update_data["variance_pct"] = round(((exp - act) / exp * 100), 2) if exp else None
        update_data["flagged_for_review"] = (
            abs(exp - act) > 10 or
            (update_data.get("variance_pct") is not None and abs(update_data["variance_pct"]) > 5)
        )

    # Auto-set resolved_by if status moves to matched
    if update_data.get("reconciliation_status") in ("matched", "written_off") and not recon.resolved_by:
        from datetime import datetime, timezone
        update_data["resolved_by"] = current_user.username
        update_data["resolved_at"] = datetime.now(timezone.utc)

    for field, value in update_data.items():
        setattr(recon, field, value)

    await db.flush()
    await db.refresh(recon)
    return recon
