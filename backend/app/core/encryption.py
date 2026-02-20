"""
Field-level PHI encryption using Fernet symmetric encryption.

Usage:
    from app.core.encryption import encrypt_value, decrypt_value

    ssn_encrypted = encrypt_value("123-45-6789")
    ssn_plain = decrypt_value(ssn_encrypted)
"""
from __future__ import annotations

import base64
import os
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.config import settings


def _build_fernet() -> Fernet:
    """
    Build a Fernet instance from the configured ENCRYPTION_KEY.
    If the key is a raw Fernet key (URL-safe base64, 44 chars) use it directly.
    Otherwise derive a key via PBKDF2.
    """
    key = settings.ENCRYPTION_KEY
    if not key:
        # Development fallback — generate ephemeral key (data lost on restart)
        key = Fernet.generate_key().decode()

    key_bytes = key.encode() if isinstance(key, str) else key

    # Check if it's already a valid Fernet key (44 URL-safe base64 chars)
    try:
        Fernet(key_bytes)
        return Fernet(key_bytes)
    except Exception:
        pass

    # Derive a proper Fernet key from a password-style key via PBKDF2
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"ocdr-phi-salt-v1",  # fixed salt is intentional (key is secret)
        iterations=100_000,
    )
    derived = base64.urlsafe_b64encode(kdf.derive(key_bytes))
    return Fernet(derived)


_fernet: Optional[Fernet] = None


def get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = _build_fernet()
    return _fernet


def encrypt_value(plain_text: Optional[str]) -> Optional[str]:
    """Encrypt a string value. Returns None if input is None."""
    if plain_text is None:
        return None
    return get_fernet().encrypt(plain_text.encode()).decode()


def decrypt_value(cipher_text: Optional[str]) -> Optional[str]:
    """
    Decrypt a string value encrypted by encrypt_value().
    Returns None if input is None.
    Raises ValueError on tampered / invalid tokens.
    """
    if cipher_text is None:
        return None
    try:
        return get_fernet().decrypt(cipher_text.encode()).decode()
    except InvalidToken as exc:
        raise ValueError(f"Failed to decrypt PHI field — possible data corruption: {exc}") from exc


def mask_value(plain_text: Optional[str], visible_chars: int = 4) -> Optional[str]:
    """Return a masked version of a sensitive string (e.g. '***-**-6789')."""
    if plain_text is None:
        return None
    plain_text = plain_text.replace("-", "").replace(" ", "")
    if len(plain_text) <= visible_chars:
        return "*" * len(plain_text)
    return "*" * (len(plain_text) - visible_chars) + plain_text[-visible_chars:]
