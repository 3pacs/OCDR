"""
Scan / Study model — links to appointment and captures DICOM/radiologist data.
"""
from __future__ import annotations

from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.appointment import Appointment
    from app.models.claim import Claim


class Scan(TimestampMixin, Base):
    __tablename__ = "scans"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    appointment_id: Mapped[int] = mapped_column(
        ForeignKey("appointments.id", ondelete="RESTRICT"), nullable=False, unique=True, index=True
    )

    # ── Study identifiers ─────────────────────────────────────────────────────
    accession_number: Mapped[Optional[str]] = mapped_column(String(100), unique=True, index=True)
    dicom_study_uid: Mapped[Optional[str]] = mapped_column(String(255), unique=True)
    study_description: Mapped[Optional[str]] = mapped_column(String(500))

    # ── Radiologist ───────────────────────────────────────────────────────────
    radiologist: Mapped[Optional[str]] = mapped_column(String(255))
    report_status: Mapped[str] = mapped_column(
        Enum("pending", "preliminary", "final", "amended", "corrected",
             name="report_status_enum"),
        default="pending",
        nullable=False,
    )

    # ── Billing ───────────────────────────────────────────────────────────────
    # CPT codes stored as JSON array: ["70553", "70552"]
    cpt_codes: Mapped[Optional[List]] = mapped_column(JSON, default=list)
    units: Mapped[Optional[int]] = mapped_column(Integer, default=1)
    charges: Mapped[Optional[float]] = mapped_column()

    # ── Relationships ─────────────────────────────────────────────────────────
    appointment: Mapped["Appointment"] = relationship("Appointment", back_populates="scan")
    claims: Mapped[List["Claim"]] = relationship("Claim", back_populates="scan")

    def __repr__(self) -> str:
        return (
            f"<Scan id={self.id} accession={self.accession_number!r} "
            f"status={self.report_status!r}>"
        )
