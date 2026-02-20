"""
Payment model — tracks each payment received (insurance or patient).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Date, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.patient import Patient
    from app.models.claim import Claim
    from app.models.eob import EOB


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    claim_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("claims.id", ondelete="SET NULL"), nullable=True, index=True
    )
    eob_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("eobs.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Payment details ───────────────────────────────────────────────────────
    payment_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    payment_type: Mapped[str] = mapped_column(
        Enum(
            "insurance_check", "insurance_eft", "insurance_era",
            "patient_check", "patient_credit_card", "patient_cash",
            "patient_ach", "adjustment",
            name="payment_type_enum",
        ),
        nullable=False,
    )
    amount: Mapped[float] = mapped_column(Numeric(10, 2), nullable=False)

    # ── Check / EFT info ──────────────────────────────────────────────────────
    check_number: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    check_image_path: Mapped[Optional[str]] = mapped_column(String(500))
    eob_source_file: Mapped[Optional[str]] = mapped_column(String(500))

    # ── Posting status ────────────────────────────────────────────────────────
    posting_status: Mapped[str] = mapped_column(
        Enum("pending", "posted", "rejected", "needs_review", name="posting_status_enum"),
        default="pending",
        nullable=False,
        index=True,
    )
    posted_by: Mapped[Optional[str]] = mapped_column(String(100))
    posted_date: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── Match confidence (from auto-matching engine) ───────────────────────────
    match_confidence: Mapped[Optional[float]] = mapped_column(comment="0-100 score from matching engine")
    match_pass: Mapped[Optional[str]] = mapped_column(String(50), comment="Which matching pass succeeded")

    # ── Adjustment codes from EOB ──────────────────────────────────────────────
    adjustment_codes: Mapped[Optional[str]] = mapped_column(Text, comment="JSON array of adjustment codes e.g. CO-45, PR-2")

    # ── Relationships ─────────────────────────────────────────────────────────
    patient: Mapped["Patient"] = relationship("Patient", back_populates="payments")
    claim: Mapped[Optional["Claim"]] = relationship("Claim", back_populates="payments")
    eob: Mapped[Optional["EOB"]] = relationship("EOB", back_populates="payments")

    def __repr__(self) -> str:
        return (
            f"<Payment id={self.id} amount=${self.amount} "
            f"type={self.payment_type!r} status={self.posting_status!r}>"
        )
