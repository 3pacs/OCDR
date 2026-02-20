"""
Audit log helpers.

Every INSERT / UPDATE / DELETE on any tracked table is logged to the
audit_logs table. This module provides the SQLAlchemy event hooks and
a helper to write audit entries programmatically.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

# Tables that are excluded from audit logging (to avoid infinite loops)
AUDIT_EXCLUDE_TABLES = {"audit_logs"}


def _serialize(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if hasattr(value, "__dict__"):
        return str(value)
    return value


def _row_to_dict(instance: Any) -> Dict[str, Any]:
    """Convert an ORM instance's column values to a plain dict."""
    mapper = inspect(instance.__class__)
    data = {}
    for col in mapper.columns:
        try:
            data[col.key] = _serialize(getattr(instance, col.key))
        except Exception:
            data[col.key] = None
    return data


def register_audit_hooks(Base: Any) -> None:
    """
    Attach SQLAlchemy event listeners to all mapped classes so every
    data-changing operation is recorded in the audit_logs table.

    Call this AFTER all models are imported so the mapper is fully configured.
    """
    from app.models.audit_log import AuditLog  # local import to avoid circular

    @event.listens_for(Session, "after_flush")
    def after_flush(session: Session, flush_context: Any) -> None:
        current_user = getattr(session, "_audit_user", "system")
        entries = []

        for instance in session.new:
            tbl = getattr(instance, "__tablename__", None)
            if tbl in AUDIT_EXCLUDE_TABLES:
                continue
            entries.append(
                AuditLog(
                    table_name=tbl,
                    record_id=str(getattr(instance, "id", "")),
                    action="INSERT",
                    old_values=None,
                    new_values=json.dumps(_row_to_dict(instance)),
                    changed_by=current_user,
                    changed_at=datetime.now(timezone.utc),
                )
            )

        for instance in session.dirty:
            tbl = getattr(instance, "__tablename__", None)
            if tbl in AUDIT_EXCLUDE_TABLES:
                continue
            history = {}
            mapper = inspect(instance.__class__)
            for col in mapper.columns:
                attr_history = inspect(instance).attrs[col.key].history
                if attr_history.has_changes():
                    old = attr_history.deleted[0] if attr_history.deleted else None
                    new = attr_history.added[0] if attr_history.added else None
                    if old != new:
                        history[col.key] = {"old": _serialize(old), "new": _serialize(new)}
            if history:
                entries.append(
                    AuditLog(
                        table_name=tbl,
                        record_id=str(getattr(instance, "id", "")),
                        action="UPDATE",
                        old_values=json.dumps({k: v["old"] for k, v in history.items()}),
                        new_values=json.dumps({k: v["new"] for k, v in history.items()}),
                        changed_by=current_user,
                        changed_at=datetime.now(timezone.utc),
                    )
                )

        for instance in session.deleted:
            tbl = getattr(instance, "__tablename__", None)
            if tbl in AUDIT_EXCLUDE_TABLES:
                continue
            entries.append(
                AuditLog(
                    table_name=tbl,
                    record_id=str(getattr(instance, "id", "")),
                    action="DELETE",
                    old_values=json.dumps(_row_to_dict(instance)),
                    new_values=None,
                    changed_by=current_user,
                    changed_at=datetime.now(timezone.utc),
                )
            )

        for entry in entries:
            session.add(entry)
