"""Patient model — consolidated patient demographics from crosswalk imports.

Each patient has two unique identifiers:
  - jacket_number (chart number): used internally for billing records
  - topaz_number (patient number): used in the Topaz billing system and ERA 835 files

All patient data is keyed to both identifiers so that looking up either one
returns the complete patient record.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Integer, JSON, String, Index
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # --- Primary identifiers ---
    jacket_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)
    topaz_number: Mapped[str | None] = mapped_column(String(50), nullable=True, index=True)

    # --- Demographics ---
    last_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    first_name: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date, nullable=True)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    state: Mapped[str | None] = mapped_column(String(10), nullable=True)
    zip_code: Mapped[str | None] = mapped_column(String(15), nullable=True)
    insurance_number: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # --- Research / billing entity ---
    is_research: Mapped[bool | None] = mapped_column(default=False)
    researcher: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)

    # --- Custom / TBD fields (raw data stored for future re-parsing) ---
    custom_data: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # --- Import tracking ---
    crosswalk_import_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    __table_args__ = (
        # Unique constraint: one patient per jacket+topaz combination
        Index("ix_patient_jacket_topaz", "jacket_number", "topaz_number", unique=True),
        # Performance indexes for name lookups
        Index("ix_patient_name", "last_name", "first_name"),
    )
