"""CrosswalkImport model — stores raw uploaded files for the 3-step
upload → examine → map → apply workflow.

Replaces the old auto-magic import that parsed and applied in one shot.
Raw file content is stored so the user can re-examine and re-map at any time.
"""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class CrosswalkImport(Base):
    __tablename__ = "crosswalk_imports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, default=0)

    # Raw file content stored as text (decoded on upload)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)

    # Auto-detected format info
    format_detected: Mapped[str] = mapped_column(String(50), nullable=False)  # fixed_width, pipe, tab, csv, xml
    format_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)
    total_records: Mapped[int] = mapped_column(Integer, default=0)

    # Parsing metadata: detected zones/headers, sample values
    # For fixed-width: [{label, start, end, width, type, sample_values}, ...]
    # For delimited: {headers: [...], delimiter: "|", header_row: 0}
    parsing_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # User-assigned field mapping: {"chart_number": "id_2", "patient_name": "name_1"}
    field_mapping: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Extracted crosswalk pairs (after user maps fields)
    extracted_pairs: Mapped[list | None] = mapped_column(JSON, nullable=True)
    extracted_count: Mapped[int] = mapped_column(Integer, default=0)

    # Application results
    applied_count: Mapped[int] = mapped_column(Integer, default=0)
    apply_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Status: UPLOADED → MAPPED → APPLIED (or REJECTED)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="UPLOADED")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    mapped_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
