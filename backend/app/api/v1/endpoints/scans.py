"""
Scan / Study CRUD endpoints.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.scan import Scan
from app.models.user import User
from app.schemas.scan import ScanCreate, ScanRead, ScanUpdate

router = APIRouter(prefix="/scans", tags=["Scans"])


@router.post(
    "/",
    response_model=ScanRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a scan/study record",
)
async def create_scan(
    body: ScanCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("scans:write")),
):
    # Check one-to-one: appointment → scan
    existing = await db.execute(select(Scan).where(Scan.appointment_id == body.appointment_id))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="A scan already exists for this appointment",
        )
    scan = Scan(**body.model_dump())
    db.add(scan)
    await db.flush()
    await db.refresh(scan)
    return scan


@router.get(
    "/{scan_id}",
    response_model=ScanRead,
    summary="Get a scan by ID",
)
async def get_scan(
    scan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("scans:read")),
):
    result = await db.execute(select(Scan).where(Scan.id == scan_id))
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    return scan


@router.get(
    "/appointment/{appointment_id}",
    response_model=ScanRead,
    summary="Get scan for a specific appointment",
)
async def get_scan_by_appointment(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("scans:read")),
):
    result = await db.execute(select(Scan).where(Scan.appointment_id == appointment_id))
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    return scan


@router.patch(
    "/{scan_id}",
    response_model=ScanRead,
    summary="Update a scan",
)
async def update_scan(
    scan_id: int,
    body: ScanUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("scans:write")),
):
    result = await db.execute(select(Scan).where(Scan.id == scan_id))
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(scan, field, value)

    await db.flush()
    await db.refresh(scan)
    return scan


@router.delete(
    "/{scan_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a scan",
)
async def delete_scan(
    scan_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("scans:write")),
):
    result = await db.execute(select(Scan).where(Scan.id == scan_id))
    scan = result.scalar_one_or_none()
    if not scan:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Scan not found")
    await db.delete(scan)
