"""
Insurance model — stores primary and secondary payer information per patient.
"""
from __future__ import annotations

from datetime import date
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Boolean, Date, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.patient import Patient
    from app.models.claim import Claim


class Insurance(TimestampMixin, Base):
    __tablename__ = "insurance"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # ── Payer info ────────────────────────────────────────────────────────────
    payer_name: Mapped[str] = mapped_column(String(255), nullable=False)
    payer_id: Mapped[Optional[str]] = mapped_column(String(50), index=True)
    plan_name: Mapped[Optional[str]] = mapped_column(String(255))

    # ── Member info ───────────────────────────────────────────────────────────
    member_id: Mapped[Optional[str]] = mapped_column(String(100), index=True)
    group_number: Mapped[Optional[str]] = mapped_column(String(100))
    subscriber_name: Mapped[Optional[str]] = mapped_column(String(255))
    relationship_to_patient: Mapped[Optional[str]] = mapped_column(
        String(50)  # self, spouse, child, other
    )

    # ── Financial ─────────────────────────────────────────────────────────────
    copay: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    deductible: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))
    out_of_pocket_max: Mapped[Optional[float]] = mapped_column(Numeric(10, 2))

    # ── Authorization ─────────────────────────────────────────────────────────
    authorization_number: Mapped[Optional[str]] = mapped_column(String(100))
    authorization_start_date: Mapped[Optional[date]] = mapped_column(Date)
    authorization_end_date: Mapped[Optional[date]] = mapped_column(Date)
    authorized_visits: Mapped[Optional[int]] = mapped_column(Integer)
    visits_used: Mapped[Optional[int]] = mapped_column(Integer, default=0)

    # ── Priority flags ────────────────────────────────────────────────────────
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_secondary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    # ── Eligibility ───────────────────────────────────────────────────────────
    eligibility_verified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    eligibility_verified_at: Mapped[Optional[date]] = mapped_column(Date)
    eligibility_response_raw: Mapped[Optional[str]] = mapped_column(Text)

    # ── Relationships ─────────────────────────────────────────────────────────
    patient: Mapped["Patient"] = relationship("Patient", back_populates="insurance")
    claims: Mapped[list["Claim"]] = relationship("Claim", back_populates="insurance")

    def __repr__(self) -> str:
        priority = "primary" if self.is_primary else ("secondary" if self.is_secondary else "other")
        return f"<Insurance id={self.id} payer={self.payer_name!r} priority={priority}>"
