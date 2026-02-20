"""
Claim model — billing claim per scan.
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.scan import Scan
    from app.models.insurance import Insurance
    from app.models.payment import Payment
    from app.models.reconciliation import Reconciliation


class Claim(TimestampMixin, Base):
    __tablename__ = "claims"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    scan_id: Mapped[int] = mapped_column(
        ForeignKey("scans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    insurance_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("insurance.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # ── Claim identifiers ─────────────────────────────────────────────────────
    claim_number: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)
    office_ally_claim_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)

    # ── Dates ─────────────────────────────────────────────────────────────────
    date_of_service: Mapped[Optional[date]] = mapped_column(Date, index=True)
    date_submitted: Mapped[Optional[date]] = mapped_column(Date)
    follow_up_date: Mapped[Optional[date]] = mapped_column(Date)

    # ── Financials ────────────────────────────────────────────────────────────
    billed_amount: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    allowed_amount: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    paid_amount: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    adjustment_amount: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    patient_responsibility: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))

    # ── Status ────────────────────────────────────────────────────────────────
    claim_status: Mapped[str] = mapped_column(
        Enum(
            "draft", "submitted", "accepted", "pending", "paid", "denied",
            "partial", "appealed", "void", "corrected",
            name="claim_status_enum",
        ),
        default="draft",
        nullable=False,
        index=True,
    )
    denial_reason: Mapped[Optional[str]] = mapped_column(Text)
    denial_code: Mapped[Optional[str]] = mapped_column(String(50), index=True)

    # ── Office Ally sync ──────────────────────────────────────────────────────
    last_synced_at: Mapped[Optional[date]] = mapped_column(Date)

    # ── Relationships ─────────────────────────────────────────────────────────
    scan: Mapped["Scan"] = relationship("Scan", back_populates="claims")
    insurance: Mapped[Optional["Insurance"]] = relationship("Insurance", back_populates="claims")
    payments: Mapped[List["Payment"]] = relationship("Payment", back_populates="claim")
    reconciliation: Mapped[Optional["Reconciliation"]] = relationship(
        "Reconciliation", back_populates="claim", uselist=False
    )

    def __repr__(self) -> str:
        return (
            f"<Claim id={self.id} claim_number={self.claim_number!r} "
            f"status={self.claim_status!r} billed=${self.billed_amount}>"
        )
