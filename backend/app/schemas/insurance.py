from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class InsuranceBase(BaseModel):
    patient_id: int
    payer_name: str
    payer_id: Optional[str] = None
    plan_name: Optional[str] = None
    member_id: Optional[str] = None
    group_number: Optional[str] = None
    subscriber_name: Optional[str] = None
    relationship_to_patient: Optional[str] = None
    copay: Optional[float] = None
    deductible: Optional[float] = None
    out_of_pocket_max: Optional[float] = None
    authorization_number: Optional[str] = None
    authorization_start_date: Optional[date] = None
    authorization_end_date: Optional[date] = None
    authorized_visits: Optional[int] = None
    visits_used: Optional[int] = 0
    is_primary: bool = False
    is_secondary: bool = False
    is_active: bool = True


class InsuranceCreate(InsuranceBase):
    pass


class InsuranceUpdate(BaseModel):
    payer_name: Optional[str] = None
    payer_id: Optional[str] = None
    plan_name: Optional[str] = None
    member_id: Optional[str] = None
    group_number: Optional[str] = None
    subscriber_name: Optional[str] = None
    relationship_to_patient: Optional[str] = None
    copay: Optional[float] = None
    deductible: Optional[float] = None
    out_of_pocket_max: Optional[float] = None
    authorization_number: Optional[str] = None
    authorization_start_date: Optional[date] = None
    authorization_end_date: Optional[date] = None
    authorized_visits: Optional[int] = None
    visits_used: Optional[int] = None
    is_primary: Optional[bool] = None
    is_secondary: Optional[bool] = None
    is_active: Optional[bool] = None
    eligibility_verified: Optional[bool] = None
    eligibility_verified_at: Optional[date] = None


class InsuranceRead(InsuranceBase):
    id: int
    eligibility_verified: Optional[bool] = None
    eligibility_verified_at: Optional[date] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
