from __future__ import annotations

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class ReconciliationBase(BaseModel):
    claim_id: int
    expected_payment: Optional[float] = None
    actual_payment: Optional[float] = None
    variance: Optional[float] = None
    variance_pct: Optional[float] = None
    reconciliation_status: str = "unmatched"
    flagged_for_review: bool = False
    notes: Optional[str] = None


class ReconciliationCreate(ReconciliationBase):
    pass


class ReconciliationUpdate(BaseModel):
    expected_payment: Optional[float] = None
    actual_payment: Optional[float] = None
    variance: Optional[float] = None
    variance_pct: Optional[float] = None
    reconciliation_status: Optional[str] = None
    flagged_for_review: Optional[bool] = None
    notes: Optional[str] = None
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None


class ReconciliationRead(ReconciliationBase):
    id: int
    resolved_by: Optional[str] = None
    resolved_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
