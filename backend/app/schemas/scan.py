from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel


class ScanBase(BaseModel):
    appointment_id: int
    accession_number: Optional[str] = None
    dicom_study_uid: Optional[str] = None
    study_description: Optional[str] = None
    radiologist: Optional[str] = None
    report_status: str = "pending"
    cpt_codes: Optional[List[str]] = None
    units: Optional[int] = 1
    charges: Optional[float] = None


class ScanCreate(ScanBase):
    pass


class ScanUpdate(BaseModel):
    accession_number: Optional[str] = None
    dicom_study_uid: Optional[str] = None
    study_description: Optional[str] = None
    radiologist: Optional[str] = None
    report_status: Optional[str] = None
    cpt_codes: Optional[List[str]] = None
    units: Optional[int] = None
    charges: Optional[float] = None


class ScanRead(ScanBase):
    id: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
