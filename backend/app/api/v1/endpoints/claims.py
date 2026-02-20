"""
Claims CRUD endpoints with AR aging and denial-pattern tracking.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.claim import Claim
from app.models.learning import DenialPattern
from app.models.user import User
from app.schemas.claim import ClaimCreate, ClaimRead, ClaimUpdate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/claims", tags=["Claims"])


@router.post(
    "/",
    response_model=ClaimRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a billing claim",
)
async def create_claim(
    body: ClaimCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("claims:write")),
):
    claim = Claim(**body.model_dump())
    db.add(claim)
    await db.flush()
    await db.refresh(claim)
    return claim


@router.get(
    "/",
    response_model=PaginatedResponse[ClaimRead],
    summary="List claims with filters",
)
async def list_claims(
    scan_id: Optional[int] = None,
    insurance_id: Optional[int] = None,
    claim_status: Optional[str] = None,
    denial_code: Optional[str] = None,
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("claims:read")),
):
    q = select(Claim)
    filters = []
    if scan_id:
        filters.append(Claim.scan_id == scan_id)
    if insurance_id:
        filters.append(Claim.insurance_id == insurance_id)
    if claim_status:
        filters.append(Claim.claim_status == claim_status)
    if denial_code:
        filters.append(Claim.denial_code == denial_code)
    if date_from:
        filters.append(Claim.date_of_service >= date_from)
    if date_to:
        filters.append(Claim.date_of_service <= date_to)
    if filters:
        q = q.where(and_(*filters))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(
        q.order_by(Claim.date_of_service.desc()).offset(offset).limit(page_size)
    )
    items = result.scalars().all()

    return PaginatedResponse(
        items=[ClaimRead.model_validate(c) for c in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/ar-aging",
    response_model=Dict[str, float],
    summary="AR aging summary — totals by 30/60/90/120+ day buckets",
)
async def get_ar_aging(
    insurance_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("claims:read")),
):
    """
    Returns sum of billed_amount for unpaid claims grouped into aging buckets.
    Only considers claims in submitted/accepted/pending/partial status.
    """
    today = date.today()
    open_statuses = ("submitted", "accepted", "pending", "partial", "denied")

    q = select(Claim).where(Claim.claim_status.in_(open_statuses))
    if insurance_id:
        q = q.where(Claim.insurance_id == insurance_id)

    result = await db.execute(q)
    claims = result.scalars().all()

    buckets: Dict[str, float] = {"0_30": 0.0, "31_60": 0.0, "61_90": 0.0, "91_120": 0.0, "120_plus": 0.0}
    for c in claims:
        if not c.date_submitted or not c.billed_amount:
            continue
        days = (today - c.date_submitted).days
        amt = float(c.billed_amount)
        if days <= 30:
            buckets["0_30"] += amt
        elif days <= 60:
            buckets["31_60"] += amt
        elif days <= 90:
            buckets["61_90"] += amt
        elif days <= 120:
            buckets["91_120"] += amt
        else:
            buckets["120_plus"] += amt

    return buckets


@router.get(
    "/{claim_id}",
    response_model=ClaimRead,
    summary="Get a claim by ID",
)
async def get_claim(
    claim_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("claims:read")),
):
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    return claim


@router.patch(
    "/{claim_id}",
    response_model=ClaimRead,
    summary="Update a claim",
)
async def update_claim(
    claim_id: int,
    body: ClaimUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("claims:write")),
):
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")

    update_data = body.model_dump(exclude_unset=True)

    # Track denial pattern changes
    old_denial_code = claim.denial_code
    new_denial_code = update_data.get("denial_code")
    new_status = update_data.get("claim_status", claim.claim_status)

    for field, value in update_data.items():
        setattr(claim, field, value)

    # If claim is being denied and denial code changed, update DenialPattern
    if new_status == "denied" and new_denial_code and new_denial_code != old_denial_code:
        await _upsert_denial_pattern(db, claim, new_denial_code)

    await db.flush()
    await db.refresh(claim)
    return claim


async def _upsert_denial_pattern(db: AsyncSession, claim: Claim, denial_code: str) -> None:
    """Update or create a DenialPattern record for analytics."""
    from app.models.scan import Scan
    from app.models.insurance import Insurance
    from datetime import datetime, timezone

    # Get CPT codes and payer info
    scan_result = await db.execute(select(Scan).where(Scan.id == claim.scan_id))
    scan = scan_result.scalar_one_or_none()
    cpt = (scan.cpt_codes or [""])[0] if scan else None

    payer_name = None
    if claim.insurance_id:
        ins_result = await db.execute(select(Insurance).where(Insurance.id == claim.insurance_id))
        ins = ins_result.scalar_one_or_none()
        if ins:
            payer_name = ins.payer_name

    existing = await db.execute(
        select(DenialPattern).where(
            and_(
                DenialPattern.denial_code == denial_code,
                DenialPattern.payer_name == payer_name,
                DenialPattern.cpt_code == cpt,
            )
        )
    )
    pattern = existing.scalar_one_or_none()
    if pattern:
        pattern.occurrence_count += 1
        pattern.total_denied_amount = (pattern.total_denied_amount or 0) + float(claim.billed_amount or 0)
        pattern.last_seen_at = datetime.now(timezone.utc)
    else:
        db.add(DenialPattern(
            payer_name=payer_name,
            cpt_code=cpt,
            denial_code=denial_code,
            denial_reason=claim.denial_reason,
            occurrence_count=1,
            total_denied_amount=float(claim.billed_amount or 0),
            last_seen_at=datetime.now(timezone.utc),
        ))


@router.delete(
    "/{claim_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Void / delete a claim",
)
async def delete_claim(
    claim_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("claims:write")),
):
    result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = result.scalar_one_or_none()
    if not claim:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Claim not found")
    await db.delete(claim)
