from __future__ import annotations

from datetime import date, datetime, time
from typing import Optional

from pydantic import BaseModel


VALID_MODALITIES = {"MRI", "PET", "CT", "PET_CT", "BONE_SCAN", "XRAY", "ULTRASOUND", "OTHER"}
VALID_STATUSES = {"scheduled", "completed", "cancelled", "no_show", "rescheduled"}


class AppointmentBase(BaseModel):
    patient_id: int
    scan_date: date
    scan_time: Optional[time] = None
    modality: str
    body_part: Optional[str] = None
    referring_physician: Optional[str] = None
    ordering_physician: Optional[str] = None
    ordering_npi: Optional[str] = None
    facility_location: Optional[str] = None
    technologist: Optional[str] = None
    status: str = "scheduled"
    notes: Optional[str] = None


class AppointmentCreate(AppointmentBase):
    source_file: Optional[str] = None
    extraction_confidence: Optional[float] = None
    raw_extracted_text: Optional[str] = None


class AppointmentUpdate(BaseModel):
    scan_date: Optional[date] = None
    scan_time: Optional[time] = None
    modality: Optional[str] = None
    body_part: Optional[str] = None
    referring_physician: Optional[str] = None
    ordering_physician: Optional[str] = None
    ordering_npi: Optional[str] = None
    facility_location: Optional[str] = None
    technologist: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None


class AppointmentRead(AppointmentBase):
    id: int
    source_file: Optional[str] = None
    extraction_confidence: Optional[float] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
