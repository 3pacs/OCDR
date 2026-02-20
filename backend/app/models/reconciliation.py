"""
Reconciliation model — tracks expected vs actual payments per claim.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.claim import Claim


class Reconciliation(TimestampMixin, Base):
    __tablename__ = "reconciliation"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    claim_id: Mapped[int] = mapped_column(
        ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    # ── Amounts ───────────────────────────────────────────────────────────────
    expected_payment: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    actual_payment: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    variance: Mapped[Optional[float]] = mapped_column(
        Numeric(10, 2), comment="expected_payment - actual_payment"
    )
    variance_pct: Mapped[Optional[float]] = mapped_column(
        comment="Variance as a percentage of expected_payment"
    )

    # ── Status ────────────────────────────────────────────────────────────────
    reconciliation_status: Mapped[str] = mapped_column(
        Enum("matched", "partial", "unmatched", "disputed", "written_off",
             name="recon_status_enum"),
        default="unmatched",
        nullable=False,
        index=True,
    )
    flagged_for_review: Mapped[bool] = mapped_column(
        default=False, nullable=False,
        comment="True when |variance| > $10 or > 5%"
    )

    # ── Resolution ────────────────────────────────────────────────────────────
    notes: Mapped[Optional[str]] = mapped_column(Text)
    resolved_by: Mapped[Optional[str]] = mapped_column(String(100))
    resolved_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # ── Relationships ─────────────────────────────────────────────────────────
    claim: Mapped["Claim"] = relationship("Claim", back_populates="reconciliation")

    def __repr__(self) -> str:
        return (
            f"<Reconciliation id={self.id} claim_id={self.claim_id} "
            f"status={self.reconciliation_status!r} variance=${self.variance}>"
        )
