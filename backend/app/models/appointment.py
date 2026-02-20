"""
Appointment / Schedule model.
"""
from __future__ import annotations

from datetime import date, time
from typing import Optional, TYPE_CHECKING

from sqlalchemy import Date, Enum, ForeignKey, Integer, String, Text, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.patient import Patient
    from app.models.scan import Scan


class Appointment(TimestampMixin, Base):
    __tablename__ = "appointments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    patient_id: Mapped[int] = mapped_column(
        ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # ── Schedule ──────────────────────────────────────────────────────────────
    scan_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    scan_time: Mapped[Optional[time]] = mapped_column(Time)

    # ── Procedure ─────────────────────────────────────────────────────────────
    modality: Mapped[str] = mapped_column(
        Enum("MRI", "PET", "CT", "PET_CT", "BONE_SCAN", "XRAY", "ULTRASOUND", "OTHER",
             name="modality_enum"),
        nullable=False,
        index=True,
    )
    body_part: Mapped[Optional[str]] = mapped_column(String(200))

    # ── Physicians ────────────────────────────────────────────────────────────
    referring_physician: Mapped[Optional[str]] = mapped_column(String(255))
    ordering_physician: Mapped[Optional[str]] = mapped_column(String(255))
    ordering_npi: Mapped[Optional[str]] = mapped_column(String(20))

    # ── Facility ──────────────────────────────────────────────────────────────
    facility_location: Mapped[Optional[str]] = mapped_column(String(255))
    technologist: Mapped[Optional[str]] = mapped_column(String(255))

    # ── Status ────────────────────────────────────────────────────────────────
    status: Mapped[str] = mapped_column(
        Enum("scheduled", "completed", "cancelled", "no_show", "rescheduled",
             name="appointment_status_enum"),
        default="scheduled",
        nullable=False,
        index=True,
    )
    notes: Mapped[Optional[str]] = mapped_column(Text)

    # ── Ingestion metadata ────────────────────────────────────────────────────
    source_file: Mapped[Optional[str]] = mapped_column(String(500), comment="PDF filename this appointment came from")
    extraction_confidence: Mapped[Optional[float]] = mapped_column(comment="OCR/parse confidence 0-100")
    raw_extracted_text: Mapped[Optional[str]] = mapped_column(Text, comment="Raw text extracted from source PDF")

    # ── Relationships ─────────────────────────────────────────────────────────
    patient: Mapped["Patient"] = relationship("Patient", back_populates="appointments")
    scan: Mapped[Optional["Scan"]] = relationship("Scan", back_populates="appointment", uselist=False)

    def __repr__(self) -> str:
        return (
            f"<Appointment id={self.id} patient_id={self.patient_id} "
            f"date={self.scan_date} modality={self.modality!r} status={self.status!r}>"
        )
