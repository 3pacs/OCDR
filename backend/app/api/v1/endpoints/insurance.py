"""
Insurance CRUD endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.insurance import Insurance
from app.models.user import User
from app.schemas.common import PaginatedResponse
from app.schemas.insurance import InsuranceCreate, InsuranceRead, InsuranceUpdate

router = APIRouter(prefix="/insurance", tags=["Insurance"])


@router.post(
    "/",
    response_model=InsuranceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Add insurance record for a patient",
)
async def create_insurance(
    body: InsuranceCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("insurance:write")),
):
    ins = Insurance(**body.model_dump())
    db.add(ins)
    await db.flush()
    await db.refresh(ins)
    return ins


@router.get(
    "/patient/{patient_id}",
    response_model=list[InsuranceRead],
    summary="Get all insurance records for a patient",
)
async def get_patient_insurance(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("insurance:read")),
):
    result = await db.execute(
        select(Insurance)
        .where(Insurance.patient_id == patient_id)
        .order_by(Insurance.is_primary.desc(), Insurance.is_secondary.desc())
    )
    return result.scalars().all()


@router.get(
    "/{insurance_id}",
    response_model=InsuranceRead,
    summary="Get an insurance record by ID",
)
async def get_insurance(
    insurance_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("insurance:read")),
):
    result = await db.execute(select(Insurance).where(Insurance.id == insurance_id))
    ins = result.scalar_one_or_none()
    if not ins:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insurance record not found")
    return ins


@router.patch(
    "/{insurance_id}",
    response_model=InsuranceRead,
    summary="Update an insurance record",
)
async def update_insurance(
    insurance_id: int,
    body: InsuranceUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("insurance:write")),
):
    result = await db.execute(select(Insurance).where(Insurance.id == insurance_id))
    ins = result.scalar_one_or_none()
    if not ins:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insurance record not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ins, field, value)

    await db.flush()
    await db.refresh(ins)
    return ins


@router.delete(
    "/{insurance_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an insurance record",
)
async def delete_insurance(
    insurance_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("insurance:write")),
):
    result = await db.execute(select(Insurance).where(Insurance.id == insurance_id))
    ins = result.scalar_one_or_none()
    if not ins:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Insurance record not found")
    await db.delete(ins)
