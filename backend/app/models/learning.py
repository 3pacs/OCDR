"""
Learning / Intelligence Layer models:
  - Correction:       staff-corrected extraction → training examples
  - PayerTemplate:    auto-generated payer extraction templates
  - BusinessRule:     staff-entered payment rules per payer/CPT
  - DenialPattern:    aggregated denial analytics
  - APICallLog:       log of every outbound API call (OA, Purview)
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, Float, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin


class Correction(TimestampMixin, Base):
    """Staff correction → stored as training data for future extractions."""
    __tablename__ = "corrections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    source_document_type: Mapped[str] = mapped_column(
        Enum("schedule", "eob", "payment", name="doc_type_enum"), nullable=False
    )
    payer_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    field_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    original_extracted_value: Mapped[Optional[str]] = mapped_column(Text)
    corrected_value: Mapped[Optional[str]] = mapped_column(Text)
    document_path: Mapped[Optional[str]] = mapped_column(String(500))
    corrected_by: Mapped[Optional[str]] = mapped_column(String(100))

    def __repr__(self) -> str:
        return (
            f"<Correction id={self.id} field={self.field_name!r} "
            f"payer={self.payer_name!r}>"
        )


class PayerTemplate(TimestampMixin, Base):
    """
    Auto-generated extraction template for a specific payer.
    Generated after PAYER_TEMPLATE_MIN_EXTRACTIONS successful extractions.
    """
    __tablename__ = "payer_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payer_name: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)

    # JSON: {field_name: {keywords: [...], regex: "...", position: {...}}}
    field_patterns: Mapped[Optional[dict]] = mapped_column(JSON)
    extraction_count: Mapped[int] = mapped_column(Integer, default=0)
    success_rate: Mapped[Optional[float]] = mapped_column(Float, comment="0.0 to 1.0")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return (
            f"<PayerTemplate id={self.id} payer={self.payer_name!r} "
            f"count={self.extraction_count} rate={self.success_rate}>"
        )


class BusinessRule(TimestampMixin, Base):
    """
    Staff-entered business rule for expected payment calculations.
    Example: "Payer X pays 80% of Medicare rate for CPT 70553"
    """
    __tablename__ = "business_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    rule_name: Mapped[str] = mapped_column(String(255), nullable=False)
    payer_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    payer_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    cpt_code: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    modality: Mapped[Optional[str]] = mapped_column(String(50))

    # Rule definition
    rule_type: Mapped[str] = mapped_column(
        Enum("pct_of_billed", "pct_of_medicare", "fixed_amount", "formula",
             name="rule_type_enum"),
        nullable=False,
    )
    # JSON: {"percentage": 0.80} or {"amount": 150.00} or {"formula": "..."}
    rule_params: Mapped[Optional[dict]] = mapped_column(JSON)
    description: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_by: Mapped[Optional[str]] = mapped_column(String(100))

    def __repr__(self) -> str:
        return (
            f"<BusinessRule id={self.id} name={self.rule_name!r} "
            f"payer={self.payer_name!r} cpt={self.cpt_code!r}>"
        )


class DenialPattern(TimestampMixin, Base):
    """
    Aggregated denial analytics — updated whenever a claim is denied.
    """
    __tablename__ = "denial_patterns"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    payer_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    payer_id: Mapped[Optional[str]] = mapped_column(String(50))
    cpt_code: Mapped[Optional[str]] = mapped_column(String(20), index=True)
    denial_code: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    denial_reason: Mapped[Optional[str]] = mapped_column(Text)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    total_denied_amount: Mapped[Optional[float]] = mapped_column(Float)
    last_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return (
            f"<DenialPattern id={self.id} code={self.denial_code!r} "
            f"payer={self.payer_name!r} count={self.occurrence_count}>"
        )


class APICallLog(TimestampMixin, Base):
    """
    Log of every outbound API call (Office Ally, Purview).
    """
    __tablename__ = "api_call_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    service: Mapped[str] = mapped_column(
        Enum("office_ally", "purview", "other", name="api_service_enum"), nullable=False, index=True
    )
    endpoint: Mapped[str] = mapped_column(String(500), nullable=False)
    method: Mapped[str] = mapped_column(String(10), nullable=False)
    request_payload: Mapped[Optional[str]] = mapped_column(Text)
    response_status: Mapped[Optional[int]] = mapped_column(Integer)
    response_body: Mapped[Optional[str]] = mapped_column(Text)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer)
    success: Mapped[Optional[bool]] = mapped_column(Boolean)
    error_message: Mapped[Optional[str]] = mapped_column(Text)

    def __repr__(self) -> str:
        return (
            f"<APICallLog id={self.id} service={self.service!r} "
            f"endpoint={self.endpoint!r} status={self.response_status}>"
        )
