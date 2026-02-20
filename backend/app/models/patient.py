"""
Patient model — core demographic entity.
SSN is stored encrypted (Fernet).
"""
from __future__ import annotations

from datetime import date
from typing import List, Optional, TYPE_CHECKING

from sqlalchemy import Date, Enum, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.base import TimestampMixin

if TYPE_CHECKING:
    from app.models.insurance import Insurance
    from app.models.appointment import Appointment
    from app.models.payment import Payment


class Patient(TimestampMixin, Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # ── Identifiers ──────────────────────────────────────────────────────────
    mrn: Mapped[str] = mapped_column(String(50), unique=True, index=True, nullable=False)

    # ── Demographics ─────────────────────────────────────────────────────────
    first_name: Mapped[str] = mapped_column(String(100), nullable=False)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False)
    dob: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    gender: Mapped[Optional[str]] = mapped_column(
        Enum("M", "F", "O", "U", name="gender_enum"), nullable=True
    )

    # ── Contact ───────────────────────────────────────────────────────────────
    address_line1: Mapped[Optional[str]] = mapped_column(String(200))
    address_line2: Mapped[Optional[str]] = mapped_column(String(200))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    state: Mapped[Optional[str]] = mapped_column(String(2))
    zip_code: Mapped[Optional[str]] = mapped_column(String(10))
    phone: Mapped[Optional[str]] = mapped_column(String(20))
    email: Mapped[Optional[str]] = mapped_column(String(255))

    # ── PHI — stored encrypted ────────────────────────────────────────────────
    ssn_encrypted: Mapped[Optional[str]] = mapped_column(
        String(512), nullable=True, comment="Fernet-encrypted SSN"
    )

    # ── Ingestion metadata ────────────────────────────────────────────────────
    verification_status: Mapped[str] = mapped_column(
        Enum("verified", "needs_verification", "flagged", name="patient_verification_enum"),
        default="needs_verification",
        nullable=False,
    )
    source_file: Mapped[Optional[str]] = mapped_column(String(500))
    extraction_confidence: Mapped[Optional[float]] = mapped_column()

    # ── Relationships ─────────────────────────────────────────────────────────
    insurance: Mapped[List["Insurance"]] = relationship(
        "Insurance", back_populates="patient", cascade="all, delete-orphan"
    )
    appointments: Mapped[List["Appointment"]] = relationship(
        "Appointment", back_populates="patient"
    )
    payments: Mapped[List["Payment"]] = relationship(
        "Payment", back_populates="patient"
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}"

    def __repr__(self) -> str:
        return f"<Patient id={self.id} mrn={self.mrn!r} name={self.full_name!r}>"
