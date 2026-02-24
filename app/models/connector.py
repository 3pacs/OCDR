from datetime import datetime, timezone
from app.extensions import db


class ConnectorCredential(db.Model):
    """Encrypted login credentials for a third-party site connector."""
    __tablename__ = "connector_credentials"

    id = db.Column(db.Integer, primary_key=True)
    connector_slug = db.Column(db.String(60), nullable=False, unique=True)
    display_name = db.Column(db.String(120))
    username = db.Column(db.Text)             # encrypted
    password = db.Column(db.Text)             # encrypted
    extra_config = db.Column(db.Text)         # encrypted JSON (2FA secret, org ID, etc.)
    active = db.Column(db.Boolean, default=True)
    last_sync_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime,
                           default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    sync_logs = db.relationship("ConnectorSyncLog", back_populates="credential",
                                lazy="dynamic", cascade="all, delete-orphan")

    def to_dict(self):
        return {
            "id": self.id,
            "connector_slug": self.connector_slug,
            "display_name": self.display_name,
            "active": self.active,
            "last_sync_at": self.last_sync_at.isoformat() if self.last_sync_at else None,
            "has_credentials": bool(self.username),
        }


class ConnectorSyncLog(db.Model):
    """One record per sync run for a connector."""
    __tablename__ = "connector_sync_logs"

    id = db.Column(db.Integer, primary_key=True)
    credential_id = db.Column(db.Integer, db.ForeignKey("connector_credentials.id"),
                              nullable=False)
    status = db.Column(db.String(20), default="running")  # running, success, failed
    records_fetched = db.Column(db.Integer, default=0)
    records_new = db.Column(db.Integer, default=0)
    message = db.Column(db.Text)
    error = db.Column(db.Text)
    started_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    finished_at = db.Column(db.DateTime)

    credential = db.relationship("ConnectorCredential", back_populates="sync_logs")

    def to_dict(self):
        return {
            "id": self.id,
            "credential_id": self.credential_id,
            "connector_slug": self.credential.connector_slug if self.credential else None,
            "status": self.status,
            "records_fetched": self.records_fetched,
            "records_new": self.records_new,
            "message": self.message,
            "error": self.error,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "finished_at": self.finished_at.isoformat() if self.finished_at else None,
        }
