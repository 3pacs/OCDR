"""
Appointment / Schedule CRUD endpoints.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.appointment import Appointment
from app.models.user import User
from app.schemas.appointment import AppointmentCreate, AppointmentRead, AppointmentUpdate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/appointments", tags=["Appointments"])


@router.post(
    "/",
    response_model=AppointmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create an appointment",
)
async def create_appointment(
    body: AppointmentCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("appointments:write")),
):
    appt = Appointment(**body.model_dump())
    db.add(appt)
    await db.flush()
    await db.refresh(appt)
    return appt


@router.get(
    "/",
    response_model=PaginatedResponse[AppointmentRead],
    summary="List appointments with filters",
)
async def list_appointments(
    patient_id: Optional[int] = None,
    modality: Optional[str] = None,
    status_filter: Optional[str] = Query(None, alias="status"),
    date_from: Optional[date] = None,
    date_to: Optional[date] = None,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("appointments:read")),
):
    q = select(Appointment)
    filters = []
    if patient_id is not None:
        filters.append(Appointment.patient_id == patient_id)
    if modality:
        filters.append(Appointment.modality == modality)
    if status_filter:
        filters.append(Appointment.status == status_filter)
    if date_from:
        filters.append(Appointment.scan_date >= date_from)
    if date_to:
        filters.append(Appointment.scan_date <= date_to)
    if filters:
        q = q.where(and_(*filters))

    total = (await db.execute(select(func.count()).select_from(q.subquery()))).scalar_one()
    offset = (page - 1) * page_size
    result = await db.execute(
        q.order_by(Appointment.scan_date.desc(), Appointment.scan_time)
        .offset(offset)
        .limit(page_size)
    )
    items = result.scalars().all()

    return PaginatedResponse(
        items=[AppointmentRead.model_validate(a) for a in items],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/today",
    response_model=List[AppointmentRead],
    summary="Get today's appointments",
)
async def get_today_appointments(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("appointments:read")),
):
    today = date.today()
    result = await db.execute(
        select(Appointment)
        .where(Appointment.scan_date == today)
        .order_by(Appointment.scan_time)
    )
    return result.scalars().all()


@router.get(
    "/{appointment_id}",
    response_model=AppointmentRead,
    summary="Get an appointment by ID",
)
async def get_appointment(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("appointments:read")),
):
    result = await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    return appt


@router.patch(
    "/{appointment_id}",
    response_model=AppointmentRead,
    summary="Update an appointment",
)
async def update_appointment(
    appointment_id: int,
    body: AppointmentUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("appointments:write")),
):
    result = await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(appt, field, value)

    await db.flush()
    await db.refresh(appt)
    return appt


@router.delete(
    "/{appointment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an appointment",
)
async def delete_appointment(
    appointment_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("appointments:write")),
):
    result = await db.execute(select(Appointment).where(Appointment.id == appointment_id))
    appt = result.scalar_one_or_none()
    if not appt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Appointment not found")
    await db.delete(appt)
