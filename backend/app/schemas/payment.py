from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel


class PaymentBase(BaseModel):
    patient_id: int
    claim_id: Optional[int] = None
    eob_id: Optional[int] = None
    payment_date: date
    payment_type: str
    amount: float
    check_number: Optional[str] = None
    check_image_path: Optional[str] = None
    eob_source_file: Optional[str] = None
    posting_status: str = "pending"
    adjustment_codes: Optional[str] = None


class PaymentCreate(PaymentBase):
    pass


class PaymentUpdate(BaseModel):
    claim_id: Optional[int] = None
    eob_id: Optional[int] = None
    payment_date: Optional[date] = None
    payment_type: Optional[str] = None
    amount: Optional[float] = None
    check_number: Optional[str] = None
    check_image_path: Optional[str] = None
    posting_status: Optional[str] = None
    posted_by: Optional[str] = None
    match_confidence: Optional[float] = None
    match_pass: Optional[str] = None
    adjustment_codes: Optional[str] = None


class PaymentRead(PaymentBase):
    id: int
    match_confidence: Optional[float] = None
    match_pass: Optional[str] = None
    posted_by: Optional[str] = None
    posted_date: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
