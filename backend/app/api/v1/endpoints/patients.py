"""
Patient CRUD endpoints with fuzzy search and SSN encryption.
"""
from __future__ import annotations

import uuid
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from rapidfuzz import fuzz, process
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_role
from app.core.encryption import decrypt_value, encrypt_value, mask_value
from app.models.patient import Patient
from app.models.user import User
from app.schemas.patient import PatientCreate, PatientRead, PatientSummary, PatientUpdate
from app.schemas.common import PaginatedResponse

router = APIRouter(prefix="/patients", tags=["Patients"])


def _generate_mrn() -> str:
    """Generate a unique Medical Record Number."""
    return f"MRN-{uuid.uuid4().hex[:8].upper()}"


def _build_patient_read(patient: Patient) -> PatientRead:
    """Build PatientRead schema, adding masked SSN."""
    data = PatientRead.model_validate(patient)
    if patient.ssn_encrypted:
        try:
            plain = decrypt_value(patient.ssn_encrypted)
            data.ssn_masked = mask_value(plain)
        except Exception:
            data.ssn_masked = "***-**-****"
    return data


@router.post(
    "/",
    response_model=PatientRead,
    status_code=status.HTTP_201_CREATED,
    summary="Create a new patient",
)
async def create_patient(
    body: PatientCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("patients:write")),
):
    mrn = body.mrn or _generate_mrn()

    # Check MRN uniqueness
    existing = await db.execute(select(Patient).where(Patient.mrn == mrn))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"MRN {mrn} already exists")

    ssn_enc = encrypt_value(body.ssn) if body.ssn else None

    patient = Patient(
        mrn=mrn,
        first_name=body.first_name,
        last_name=body.last_name,
        dob=body.dob,
        gender=body.gender,
        address_line1=body.address_line1,
        address_line2=body.address_line2,
        city=body.city,
        state=body.state,
        zip_code=body.zip_code,
        phone=body.phone,
        email=str(body.email) if body.email else None,
        ssn_encrypted=ssn_enc,
    )
    db.add(patient)
    await db.flush()
    await db.refresh(patient)
    return _build_patient_read(patient)


@router.get(
    "/",
    response_model=PaginatedResponse[PatientSummary],
    summary="List patients with optional search",
)
async def list_patients(
    q: Optional[str] = Query(None, description="Search by name, MRN, or phone"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("patients:read")),
):
    offset = (page - 1) * page_size
    base_q = select(Patient)

    if q:
        q_like = f"%{q}%"
        base_q = base_q.where(
            or_(
                Patient.mrn.ilike(q_like),
                Patient.first_name.ilike(q_like),
                Patient.last_name.ilike(q_like),
                Patient.phone.ilike(q_like),
            )
        )

    count_q = select(func.count()).select_from(base_q.subquery())
    total = (await db.execute(count_q)).scalar_one()

    result = await db.execute(
        base_q.order_by(Patient.last_name, Patient.first_name)
        .offset(offset)
        .limit(page_size)
    )
    patients = result.scalars().all()

    return PaginatedResponse(
        items=[PatientSummary.model_validate(p) for p in patients],
        total=total,
        page=page,
        page_size=page_size,
        pages=(total + page_size - 1) // page_size,
    )


@router.get(
    "/fuzzy-search",
    response_model=List[PatientSummary],
    summary="Fuzzy-search patients by name (used during document ingestion)",
)
async def fuzzy_search_patients(
    name: str = Query(..., min_length=2),
    threshold: int = Query(85, ge=50, le=100),
    limit: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("patients:read")),
):
    result = await db.execute(select(Patient))
    all_patients = result.scalars().all()

    names = {p.id: p.full_name for p in all_patients}
    matches = process.extract(
        name, names, scorer=fuzz.token_sort_ratio, limit=limit, score_cutoff=threshold
    )

    matched_ids = {match[2] for match in matches}
    return [
        PatientSummary.model_validate(p)
        for p in all_patients
        if p.id in matched_ids
    ]


@router.get(
    "/{patient_id}",
    response_model=PatientRead,
    summary="Get a patient by ID",
)
async def get_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("patients:read")),
):
    result = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return _build_patient_read(patient)


@router.get(
    "/mrn/{mrn}",
    response_model=PatientRead,
    summary="Get a patient by MRN",
)
async def get_patient_by_mrn(
    mrn: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("patients:read")),
):
    result = await db.execute(select(Patient).where(Patient.mrn == mrn))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    return _build_patient_read(patient)


@router.patch(
    "/{patient_id}",
    response_model=PatientRead,
    summary="Update a patient",
)
async def update_patient(
    patient_id: int,
    body: PatientUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("patients:write")),
):
    result = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")

    update_data = body.model_dump(exclude_unset=True)
    if "ssn" in update_data:
        patient.ssn_encrypted = encrypt_value(update_data.pop("ssn"))
    for field, value in update_data.items():
        setattr(patient, field, value)

    await db.flush()
    await db.refresh(patient)
    return _build_patient_read(patient)


@router.delete(
    "/{patient_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a patient (admin only)",
)
async def delete_patient(
    patient_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role("patients:delete")),
):
    result = await db.execute(select(Patient).where(Patient.id == patient_id))
    patient = result.scalar_one_or_none()
    if not patient:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Patient not found")
    await db.delete(patient)
