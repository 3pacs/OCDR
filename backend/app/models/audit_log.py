"""
AuditLog model — immutable record of every data change for HIPAA compliance.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class AuditLog(Base):
    """
    Append-only audit log table.
    NOTE: No TimestampMixin — we deliberately avoid updated_at on audit records.
    """
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    table_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    record_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[str] = mapped_column(
        Enum("INSERT", "UPDATE", "DELETE", name="audit_action_enum"),
        nullable=False,
        index=True,
    )

    old_values: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON snapshot before change")
    new_values: Mapped[str | None] = mapped_column(Text, nullable=True, comment="JSON snapshot after change")

    changed_by: Mapped[str] = mapped_column(String(100), nullable=False, default="system")
    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
        index=True,
    )

    def __repr__(self) -> str:
        return (
            f"<AuditLog id={self.id} table={self.table_name!r} "
            f"record={self.record_id!r} action={self.action!r}>"
        )
