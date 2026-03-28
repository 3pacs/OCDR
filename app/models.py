import os
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import Index
from cryptography.fernet import Fernet

from app import db

# ---------------------------------------------------------------------------
# Encryption helpers – key stored in env or generated once and saved
# ---------------------------------------------------------------------------
_ENCRYPTION_KEY = os.environ.get("OCDR_ENCRYPTION_KEY")
if not _ENCRYPTION_KEY:
    key_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "instance", ".encryption_key"
    )
    if os.path.exists(key_path):
        with open(key_path, "rb") as f:
            _ENCRYPTION_KEY = f.read()
    else:
        _ENCRYPTION_KEY = Fernet.generate_key()
        os.makedirs(os.path.dirname(key_path), exist_ok=True)
        with open(key_path, "wb") as f:
            f.write(_ENCRYPTION_KEY)

_fernet = Fernet(_ENCRYPTION_KEY if isinstance(_ENCRYPTION_KEY, bytes)
                 else _ENCRYPTION_KEY.encode())


def encrypt_value(value: str) -> str:
    """Encrypt a string value for storage."""
    if not value:
        return value
    return _fernet.encrypt(value.encode()).decode()


def decrypt_value(token: str) -> str:
    """Decrypt a stored encrypted value."""
    if not token:
        return token
    return _fernet.decrypt(token.encode()).decode()


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = "users"

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))


class Patient(db.Model):
    __tablename__ = "patients"

    id = db.Column(db.Integer, primary_key=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    date_of_birth = db.Column(db.Date, nullable=True)
    address = db.Column(db.Text, nullable=True)  # encrypted at rest
    phone = db.Column(db.String(50), nullable=True)  # encrypted at rest
    insurance_carrier = db.Column(db.String(100), nullable=True)
    patient_id_external = db.Column(db.String(50), nullable=True)  # external ID
    photo_filename = db.Column(db.String(256), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    updated_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc),
                           onupdate=lambda: datetime.now(timezone.utc))

    documents = db.relationship("Document", backref="patient", lazy="dynamic",
                                order_by="Document.created_at.desc()")

    __table_args__ = (
        Index("ix_patient_name", "last_name", "first_name"),
    )

    @property
    def full_name(self):
        return f"{self.last_name}, {self.first_name}"

    @property
    def decrypted_address(self):
        return decrypt_value(self.address) if self.address else None

    @decrypted_address.setter
    def decrypted_address(self, value):
        self.address = encrypt_value(value) if value else None

    @property
    def decrypted_phone(self):
        return decrypt_value(self.phone) if self.phone else None

    @decrypted_phone.setter
    def decrypted_phone(self, value):
        self.phone = encrypt_value(value) if value else None

    def to_dict(self):
        return {
            "id": self.id,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "full_name": self.full_name,
            "date_of_birth": self.date_of_birth.isoformat() if self.date_of_birth else None,
            "address": self.decrypted_address,
            "phone": self.decrypted_phone,
            "insurance_carrier": self.insurance_carrier,
            "patient_id_external": self.patient_id_external,
            "photo_filename": self.photo_filename,
            "notes": self.notes,
            "document_count": self.documents.count(),
            "created_at": self.created_at.isoformat(),
        }


class Document(db.Model):
    __tablename__ = "documents"

    id = db.Column(db.Integer, primary_key=True)
    patient_id = db.Column(db.Integer, db.ForeignKey("patients.id"), nullable=True)
    filename = db.Column(db.String(256), nullable=False)
    original_filename = db.Column(db.String(256), nullable=False)
    file_type = db.Column(db.String(20), nullable=False)  # pdf, image, etc.
    document_type = db.Column(db.String(100), nullable=True)  # ID, insurance_card, lab_result, etc.
    file_size = db.Column(db.Integer, nullable=True)

    # LLM-extracted data stored as JSON text
    extracted_data = db.Column(db.Text, nullable=True)
    raw_ocr_text = db.Column(db.Text, nullable=True)
    llm_summary = db.Column(db.Text, nullable=True)

    # Parsed fields from LLM
    parsed_name = db.Column(db.String(200), nullable=True)
    parsed_dob = db.Column(db.String(50), nullable=True)
    parsed_address = db.Column(db.Text, nullable=True)
    parsed_doc_type = db.Column(db.String(100), nullable=True)

    status = db.Column(db.String(20), default="uploaded")  # uploaded, processing, parsed, matched, filed, error
    match_confidence = db.Column(db.Float, nullable=True)
    error_message = db.Column(db.Text, nullable=True)

    created_at = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc))
    processed_at = db.Column(db.DateTime, nullable=True)

    __table_args__ = (
        Index("ix_doc_patient", "patient_id"),
        Index("ix_doc_status", "status"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "patient_id": self.patient_id,
            "filename": self.filename,
            "original_filename": self.original_filename,
            "file_type": self.file_type,
            "document_type": self.document_type,
            "file_size": self.file_size,
            "extracted_data": self.extracted_data,
            "raw_ocr_text": self.raw_ocr_text,
            "llm_summary": self.llm_summary,
            "parsed_name": self.parsed_name,
            "parsed_dob": self.parsed_dob,
            "parsed_address": self.parsed_address,
            "parsed_doc_type": self.parsed_doc_type,
            "status": self.status,
            "match_confidence": self.match_confidence,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat(),
            "processed_at": self.processed_at.isoformat() if self.processed_at else None,
            "patient_name": self.patient.full_name if self.patient else None,
        }
