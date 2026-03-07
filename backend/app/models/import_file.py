"""Import tracking model — tracks each uploaded file and its processing results."""

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class ImportFile(Base):
    __tablename__ = "import_files"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size_bytes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sheet_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    import_type: Mapped[str] = mapped_column(String(50), nullable=False)  # EXCEL_STRUCTURED, EXCEL_FLEXIBLE, ERA_835
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PROCESSING")  # PROCESSING, COMPLETED, FAILED
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_skipped: Mapped[int] = mapped_column(Integer, default=0)
    rows_errored: Mapped[int] = mapped_column(Integer, default=0)
    column_mapping: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    unmapped_columns: Mapped[list | None] = mapped_column(JSON, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
