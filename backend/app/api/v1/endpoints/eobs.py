"""
EOB CRUD endpoints — EOB ingestion queue and review workflow.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.eob import EOB, EOBLineItem
from app.models.user import User
from app.schemas.eob import EOBCreate, EOBRead, EOBUpdate, EOBLineItemRead
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/eobs", tags=["EOBs"])


@router.post(
    "/",
    response_model=EOBRead,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new EOB document",
)
async def create_eob(
    body: EOBCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("eobs:write")),
):
    eob = EOB(**body.model_dump())
    db.add(eob)
    await db.flush()
    await db.refresh(eob)
    return eob


@router.get(
    "/",
    response_model=PaginatedResponse[EOBRead],
    summary="List EOBs with filters",
)
async def list_eobs(
    processed_status: Optional[str] = None,
    payer_name: Optional[str] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("eobs:read")),
):
    q = select(EOB)
    filters = []
    if processed_status:
        filters.append(EOB.processed_status == processed_status)
    if payer_name:
        filters.append(EOB.payer_name.ilike(f"%{payer_name}%"))
    if filters:
        q = q.where(and_(*filters))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(
        q.order_by(EOB.created_at.desc()).offset(offset).limit(page_size)
    )
    items = result.scalars().all()

    return PaginatedResponse(
        items=[EOBRead.model_validate(e) for e in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/review-queue",
    response_model=list[EOBRead],
    summary="Get EOBs pending staff review",
)
async def get_review_queue(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("eobs:read")),
):
    result = await db.execute(
        select(EOB)
        .where(EOB.processed_status == "needs_review")
        .order_by(EOB.created_at.asc())
    )
    return result.scalars().all()


@router.get(
    "/{eob_id}",
    response_model=EOBRead,
    summary="Get an EOB by ID with all line items",
)
async def get_eob(
    eob_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("eobs:read")),
):
    result = await db.execute(select(EOB).where(EOB.id == eob_id))
    eob = result.scalar_one_or_none()
    if not eob:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="EOB not found")
    return eob


@router.patch(
    "/{eob_id}",
    response_model=EOBRead,
    summary="Update EOB processing status or matched claims",
)
async def update_eob(
    eob_id: int,
    body: EOBUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("eobs:write")),
):
    result = await db.execute(select(EOB).where(EOB.id == eob_id))
    eob = result.scalar_one_or_none()
    if not eob:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="EOB not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(eob, field, value)

    await db.flush()
    await db.refresh(eob)
    return eob


@router.get(
    "/{eob_id}/line-items",
    response_model=list[EOBLineItemRead],
    summary="Get all line items for an EOB",
)
async def get_eob_line_items(
    eob_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("eobs:read")),
):
    result = await db.execute(
        select(EOBLineItem).where(EOBLineItem.eob_id == eob_id)
    )
    return result.scalars().all()


@router.patch(
    "/line-items/{line_item_id}/approve",
    response_model=EOBLineItemRead,
    summary="Staff approves an EOB line item match",
)
async def approve_line_item_match(
    line_item_id: int,
    claim_id: int = Query(..., description="Confirmed claim ID to link"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("eobs:write")),
):
    result = await db.execute(select(EOBLineItem).where(EOBLineItem.id == line_item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line item not found")

    item.claim_id = claim_id
    item.match_status = "matched"
    item.match_pass = "manual_approval"

    await db.flush()
    await db.refresh(item)
    return item


@router.patch(
    "/line-items/{line_item_id}/reject",
    response_model=EOBLineItemRead,
    summary="Staff rejects an EOB line item match — returns to queue",
)
async def reject_line_item_match(
    line_item_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("eobs:write")),
):
    result = await db.execute(select(EOBLineItem).where(EOBLineItem.id == line_item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Line item not found")

    item.claim_id = None
    item.match_status = "rejected"
    item.match_confidence = None

    await db.flush()
    await db.refresh(item)
    return item
