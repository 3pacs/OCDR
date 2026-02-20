from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel


class EOBLineItemBase(BaseModel):
    patient_name_raw: Optional[str] = None
    date_of_service: Optional[date] = None
    cpt_code: Optional[str] = None
    modifier: Optional[str] = None
    units: Optional[int] = None
    billed_amount: Optional[float] = None
    allowed_amount: Optional[float] = None
    paid_amount: Optional[float] = None
    patient_responsibility: Optional[float] = None
    adjustment_codes: Optional[List[dict]] = None


class EOBLineItemRead(EOBLineItemBase):
    id: int
    eob_id: int
    claim_id: Optional[int] = None
    match_confidence: Optional[float] = None
    match_pass: Optional[str] = None
    match_status: str
    created_at: datetime

    model_config = {"from_attributes": True}


class EOBBase(BaseModel):
    raw_file_path: str
    file_type: str = "pdf"
    payer_name: Optional[str] = None
    payer_id: Optional[str] = None
    check_number: Optional[str] = None
    check_date: Optional[date] = None
    npi: Optional[str] = None
    total_paid: Optional[float] = None


class EOBCreate(EOBBase):
    pass


class EOBUpdate(BaseModel):
    payer_name: Optional[str] = None
    payer_id: Optional[str] = None
    check_number: Optional[str] = None
    check_date: Optional[date] = None
    npi: Optional[str] = None
    total_paid: Optional[float] = None
    processed_status: Optional[str] = None
    confidence_score: Optional[float] = None
    matched_claim_ids: Optional[List[int]] = None


class EOBRead(EOBBase):
    id: int
    processed_status: str
    processed_at: Optional[datetime] = None
    matched_claim_ids: Optional[List[int]] = None
    confidence_score: Optional[float] = None
    extraction_method: Optional[str] = None
    line_items: List[EOBLineItemRead] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
