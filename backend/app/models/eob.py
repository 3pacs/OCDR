"""
EOB (Explanation of Benefits) model — raw EOB ingestion and parsed line items.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.payment import Payment


class EOB(TimestampMixin, Base):
    """
    Represents a single EOB document (check or EFT remittance).
    One EOB may contain many line items / claims.
    """
    __tablename__ = "eobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Source file ───────────────────────────────────────────────────────────
    raw_file_path: Mapped[str] = mapped_column(String(500), nullable=False)
    file_type: Mapped[str] = mapped_column(
        Enum("pdf", "image", "era_835", "manual", name="eob_file_type_enum"),
        default="pdf",
    )

    # ── Parsed payer / check info ─────────────────────────────────────────────
    payer_name: Mapped[Optional[str]] = mapped_column(String(255), index=True)
    payer_id: Mapped[Optional[str]] = mapped_column(String(50))
    check_number: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    check_date: Mapped[Optional[date]] = mapped_column(Date)
    npi: Mapped[Optional[str]] = mapped_column(String(20))
    total_paid: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))

    # ── Processing status ─────────────────────────────────────────────────────
    processed_status: Mapped[str] = mapped_column(
        Enum("pending", "processing", "processed", "failed", "needs_review",
             name="eob_processed_status_enum"),
        default="pending",
        nullable=False,
        index=True,
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── Matching results ──────────────────────────────────────────────────────
    matched_claim_ids: Mapped[Optional[List]] = mapped_column(
        JSON, default=list, comment="Array of claim IDs that were matched to this EOB"
    )
    confidence_score: Mapped[Optional[float]] = mapped_column(
        comment="Overall extraction confidence 0-100"
    )

    # ── Raw extraction data ────────────────────────────────────────────────────
    raw_extracted_text: Mapped[Optional[str]] = mapped_column(Text)
    extraction_method: Mapped[Optional[str]] = mapped_column(
        Enum("pdfplumber", "tesseract", "era_835", "manual", name="extraction_method_enum")
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    line_items: Mapped[List["EOBLineItem"]] = relationship(
        "EOBLineItem", back_populates="eob", cascade="all, delete-orphan"
    )
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="eob")

    def __repr__(self) -> str:
        return (
            f"<EOB id={self.id} payer={self.payer_name!r} "
            f"check={self.check_number!r} total=${self.total_paid} status={self.processed_status!r}>"
        )


class EOBLineItem(TimestampMixin, Base):
    """
    Individual claim line within an EOB document.
    """
    __tablename__ = "eob_line_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    eob_id: Mapped[int] = mapped_column(
        ForeignKey("eobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True,
        comment="Matched claim ID after reconciliation"
    )

    # ── Patient info (as extracted from EOB) ──────────────────────────────────
    patient_name_raw: Mapped[Optional[str]] = mapped_column(String(255))
    date_of_service: Mapped[Optional[date]] = mapped_column(Date, index=True)

    # ── CPT / procedure ───────────────────────────────────────────────────────
    cpt_code: Mapped[Optional[str]] = mapped_column(String(20))
    modifier: Mapped[Optional[str]] = mapped_column(String(10))
    units: Mapped[Optional[int]] = mapped_column(Integer)

    # ── Amounts ───────────────────────────────────────────────────────────────
    billed_amount: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    allowed_amount: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    paid_amount: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    patient_responsibility: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))

    # ── Adjustment codes ──────────────────────────────────────────────────────
    # JSON array: [{"code": "CO-45", "amount": 150.00}, {"code": "PR-2", "amount": 25.00}]
    adjustment_codes: Mapped[Optional[List]] = mapped_column(JSON, default=list)

    # ── Match result ──────────────────────────────────────────────────────────
    match_confidence: Mapped[Optional[float]] = mapped_column()
    match_pass: Mapped[Optional[str]] = mapped_column(String(50))
    match_status: Mapped[str] = mapped_column(
        Enum("unmatched", "matched", "manual_review", "rejected", name="line_match_status_enum"),
        default="unmatched",
        nullable=False,
    )

    # ── Relationships ─────────────────────────────────────────────────────────
    eob: Mapped["EOB"] = relationship("EOB", back_populates="line_items")

    def __repr__(self) -> str:
        return (
            f"<EOBLineItem id={self.id} eob_id={self.eob_id} "
            f"cpt={self.cpt_code!r} paid=${self.paid_amount}>"
        )
