"""ServerSource model — stores .NET server file locations for autonomous sync.

Each source points to a directory of fixed-width text files from a .NET billing
server. The app periodically scans the directory, detects new or modified files,
parses them using the fixed-width parser with the stored field mapping, and
appends new patient data to the patients table.

Workflow:
  1. User registers a server source (directory path + field mapping)
  2. Initial sync reads all files, parses, and populates patients table
  3. Background scheduler polls for new/modified files at the configured interval
  4. New records are appended; existing records are updated with new data
"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, JSON
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.db.session import Base


class ServerSource(Base):
    __tablename__ = "server_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Display name for this source (e.g., "Main Topaz Server")
    name: Mapped[str] = mapped_column(String(200), nullable=False)

    # Path to the directory containing .NET server text files (read-only mount)
    directory_path: Mapped[str] = mapped_column(String(1000), nullable=False)

    # Field mapping from zone labels to patient roles
    # e.g., {"chart_number": "id_1", "last_name": "name_1", "first_name": "name_2",
    #        "date_of_birth": "date_1", "phone": "phone_1", ...}
    field_mapping: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Whether this source is actively polled by the scheduler
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # Polling interval in minutes (default: 60 = hourly)
    poll_interval_minutes: Mapped[int] = mapped_column(Integer, default=60)

    # File tracking: which files have been processed and their last-modified times
    # {"ptnote1.txt": {"size": 7962112, "mtime": 1709740800.0, "records": 62234}, ...}
    file_states: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Sync statistics
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    last_sync_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    total_files_processed: Mapped[int] = mapped_column(Integer, default=0)
    total_records_imported: Mapped[int] = mapped_column(Integer, default=0)

    # Status: PENDING_SETUP → ACTIVE → PAUSED → ERROR
    status: Mapped[str] = mapped_column(String(20), default="PENDING_SETUP")
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
