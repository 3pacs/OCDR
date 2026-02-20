from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class ClaimBase(BaseModel):
    scan_id: int
    insurance_id: Optional[int] = None
    claim_number: Optional[str] = None
    date_of_service: Optional[date] = None
    date_submitted: Optional[date] = None
    billed_amount: Optional[float] = None
    allowed_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    adjustment_amount: Optional[float] = None
    patient_responsibility: Optional[float] = None
    claim_status: str = "draft"
    denial_reason: Optional[str] = None
    denial_code: Optional[str] = None
    follow_up_date: Optional[date] = None


class ClaimCreate(ClaimBase):
    pass


class ClaimUpdate(BaseModel):
    claim_number: Optional[str] = None
    insurance_id: Optional[int] = None
    date_of_service: Optional[date] = None
    date_submitted: Optional[date] = None
    billed_amount: Optional[float] = None
    allowed_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    adjustment_amount: Optional[float] = None
    patient_responsibility: Optional[float] = None
    claim_status: Optional[str] = None
    denial_reason: Optional[str] = None
    denial_code: Optional[str] = None
    follow_up_date: Optional[date] = None
    office_ally_claim_id: Optional[str] = None


class ClaimRead(ClaimBase):
    id: int
    office_ally_claim_id: Optional[str] = None
    last_synced_at: Optional[date] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
