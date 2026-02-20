from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, field_validator


class PatientBase(BaseModel):
    first_name: str
    last_name: str
    dob: date
    gender: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None

    @field_validator("gender")
    @classmethod
    def validate_gender(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in ("M", "F", "O", "U"):
            raise ValueError("gender must be M, F, O, or U")
        return v


class PatientCreate(PatientBase):
    mrn: Optional[str] = None  # auto-generated if not provided
    ssn: Optional[str] = None  # plain-text on input, encrypted at storage


class PatientUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    dob: Optional[date] = None
    gender: Optional[str] = None
    address_line1: Optional[str] = None
    address_line2: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[EmailStr] = None
    ssn: Optional[str] = None
    verification_status: Optional[str] = None


class PatientRead(PatientBase):
    id: int
    mrn: str
    verification_status: str
    source_file: Optional[str] = None
    extraction_confidence: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    # SSN is never returned — only masked SSN for display
    ssn_masked: Optional[str] = None

    model_config = {"from_attributes": True}


class PatientSummary(BaseModel):
    """Lightweight patient record for list views."""
    id: int
    mrn: str
    first_name: str
    last_name: str
    dob: date
    phone: Optional[str] = None
    verification_status: str

    model_config = {"from_attributes": True}
