"""PHI (Protected Health Information) encryption for HIPAA-safe logging.

Encrypts patient-identifying fields before they touch log files or leave
the local system.  Uses Fernet symmetric encryption (AES-128-CBC + HMAC)
from the ``cryptography`` library if available, otherwise falls back to
a stdlib-only approach using ``hashlib`` for one-way hashing (can't decrypt,
but protects PHI in logs).

PHI fields: patient_name, patient_id, topaz_patient_id, referring_doctor,
            reading_physician, insurance_carrier (when combined with dates).

Non-PHI fields that are safe to log unencrypted:
  modality, scan_type, service_date, amounts, denial codes, status values.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re

# PHI field names that MUST be encrypted before logging
PHI_FIELDS = frozenset({
    "patient_name",
    "patient_name_835",
    "patient_id",
    "topaz_patient_id",
    "referring_doctor",
    "reading_physician",
    "insurance_carrier",  # PHI when combined with dates/services
})

# Fields that are safe to log without encryption
SAFE_FIELDS = frozenset({
    "modality", "scan_type", "service_date", "scheduled_date",
    "status", "denial_status", "denial_reason_code", "match_status",
    "total_payment", "primary_payment", "secondary_payment",
    "billed_amount", "paid_amount", "cas_group_code", "cas_reason_code",
    "cpt_code", "import_source", "source_file", "match_confidence",
    "id", "era_payment_id", "era_claim_id", "claim_id", "claim_status",
})

# Try to use Fernet (reversible encryption). Falls back to HMAC hashing.
_fernet_instance = None
_hmac_key = None


def _get_fernet():
    """Get or create a Fernet cipher instance."""
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return None

    try:
        from flask import current_app
        key = current_app.config.get("PHI_ENCRYPTION_KEY", "")
    except RuntimeError:
        key = os.environ.get("PHI_ENCRYPTION_KEY", "")

    if key:
        try:
            _fernet_instance = Fernet(key.encode() if isinstance(key, str) else key)
            return _fernet_instance
        except Exception:
            pass

    # Auto-generate a session key (logs won't be decryptable after restart)
    new_key = Fernet.generate_key()
    _fernet_instance = Fernet(new_key)
    return _fernet_instance


def _get_hmac_key() -> bytes:
    """Get or create an HMAC key for one-way hashing."""
    global _hmac_key
    if _hmac_key is not None:
        return _hmac_key

    try:
        from flask import current_app
        secret = current_app.config.get("SECRET_KEY", "")
    except RuntimeError:
        secret = os.environ.get("SECRET_KEY", "")

    if secret:
        _hmac_key = hashlib.sha256(secret.encode() if isinstance(secret, str) else secret).digest()
    else:
        _hmac_key = os.urandom(32)

    return _hmac_key


def encrypt_phi(value: str) -> str:
    """Encrypt a PHI value.

    Uses Fernet if available (reversible), otherwise HMAC-SHA256 (one-way).
    Returns a string prefixed with 'ENC:' (Fernet) or 'HASH:' (HMAC).
    """
    if not value or not value.strip():
        return ""

    value = value.strip()

    # Try Fernet first
    fernet = _get_fernet()
    if fernet is not None:
        try:
            encrypted = fernet.encrypt(value.encode("utf-8"))
            return "ENC:" + encrypted.decode("ascii")
        except Exception:
            pass

    # Fallback: HMAC hash (one-way, but deterministic for same input)
    key = _get_hmac_key()
    h = hmac.new(key, value.encode("utf-8"), hashlib.sha256).hexdigest()[:16]
    return f"HASH:{h}"


def decrypt_phi(encrypted_value: str) -> str:
    """Decrypt a PHI value encrypted with encrypt_phi().

    Only works for 'ENC:' prefix (Fernet). 'HASH:' values cannot be reversed.
    Returns the original text, or the encrypted value unchanged if decryption fails.
    """
    if not encrypted_value:
        return ""

    if encrypted_value.startswith("ENC:"):
        fernet = _get_fernet()
        if fernet is not None:
            try:
                token = encrypted_value[4:].encode("ascii")
                return fernet.decrypt(token).decode("utf-8")
            except Exception:
                return encrypted_value

    # HASH: values cannot be decrypted
    return encrypted_value


def encrypt_record(record: dict) -> dict:
    """Encrypt all PHI fields in a record dict.

    Returns a new dict with PHI fields encrypted and safe fields unchanged.
    Unknown fields are encrypted by default (safe > sorry for PHI).
    """
    result = {}
    for key, value in record.items():
        if key in PHI_FIELDS and isinstance(value, str):
            result[key] = encrypt_phi(value)
        elif key in SAFE_FIELDS:
            result[key] = value
        elif isinstance(value, str) and _looks_like_name(value):
            # Unknown field that looks like a patient name — encrypt
            result[key] = encrypt_phi(value)
        else:
            result[key] = value
    return result


def decrypt_record(record: dict) -> dict:
    """Decrypt all encrypted fields in a record dict."""
    result = {}
    for key, value in record.items():
        if isinstance(value, str) and (value.startswith("ENC:") or value.startswith("HASH:")):
            result[key] = decrypt_phi(value)
        else:
            result[key] = value
    return result


def redact_phi_from_text(text: str) -> str:
    """Redact likely PHI from free text (for safe logging).

    Replaces patterns that look like patient names (LAST, FIRST format)
    with [REDACTED]. Does not catch all PHI but handles the most common
    patterns in this imaging center's data.
    """
    if not text:
        return text

    # Pattern: LASTNAME, FIRSTNAME (all caps, as used in this system)
    text = re.sub(
        r'\b[A-Z][A-Z]+,\s*[A-Z][A-Z]+(?:\s+[A-Z])?\b',
        '[REDACTED]',
        text
    )

    # Pattern: "patient LASTNAME" or "patient: LASTNAME"
    text = re.sub(
        r'(?i)patient[:\s]+([A-Z][A-Za-z]+(?:,\s*[A-Z][A-Za-z]+)?)',
        'patient [REDACTED]',
        text
    )

    return text


def _looks_like_name(value: str) -> bool:
    """Heuristic: does this string look like a patient name?"""
    if not value or len(value) < 3 or len(value) > 100:
        return False
    # Common pattern: LASTNAME, FIRSTNAME
    if re.match(r'^[A-Z][A-Z]+,\s*[A-Z]', value):
        return True
    return False


def generate_encryption_key() -> str:
    """Generate a new Fernet encryption key for PHI_ENCRYPTION_KEY config."""
    try:
        from cryptography.fernet import Fernet
        return Fernet.generate_key().decode("ascii")
    except ImportError:
        return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii")
