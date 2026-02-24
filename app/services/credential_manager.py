"""
Credential manager — Fernet-encrypted storage for third-party login credentials.

The encryption key is derived from the app's SECRET_KEY using PBKDF2.
All sensitive fields (username, password, extra_config) are encrypted at rest.
"""
from __future__ import annotations

import base64
import json
import os
from typing import Any

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC


# ------------------------------------------------------------------ #
# Key derivation                                                      #
# ------------------------------------------------------------------ #

_SALT = b"OCDR_CRED_SALT_v1"   # fixed salt; change only if rotating keys


def _derive_key(secret_key: str) -> bytes:
    """Derive a 32-byte Fernet key from the app's SECRET_KEY."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=_SALT,
        iterations=100_000,
    )
    raw = kdf.derive(secret_key.encode("utf-8"))
    return base64.urlsafe_b64encode(raw)


def _get_fernet() -> Fernet:
    """Build a Fernet cipher using the current Flask app's SECRET_KEY."""
    from flask import current_app
    key = _derive_key(current_app.config["SECRET_KEY"])
    return Fernet(key)


# ------------------------------------------------------------------ #
# Public helpers                                                      #
# ------------------------------------------------------------------ #

def encrypt(plaintext: str) -> str:
    """Encrypt a string value. Returns base64-encoded ciphertext."""
    if not plaintext:
        return ""
    return _get_fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt(ciphertext: str) -> str:
    """Decrypt a previously encrypted value. Returns plaintext."""
    if not ciphertext:
        return ""
    return _get_fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")


def encrypt_dict(data: dict) -> str:
    """Serialize a dict to JSON then encrypt it."""
    return encrypt(json.dumps(data))


def decrypt_dict(ciphertext: str) -> dict:
    """Decrypt and deserialize a JSON dict."""
    if not ciphertext:
        return {}
    return json.loads(decrypt(ciphertext))


# ------------------------------------------------------------------ #
# DB-backed credential store                                          #
# ------------------------------------------------------------------ #

def save_credentials(
    connector_slug: str,
    username: str,
    password: str,
    extra: dict | None = None,
    display_name: str | None = None,
) -> "ConnectorCredential":
    """
    Create or update credentials for a connector.
    Returns the saved ConnectorCredential instance.
    """
    from app.extensions import db
    from app.models.connector import ConnectorCredential

    cred = db.session.execute(
        db.select(ConnectorCredential).where(
            ConnectorCredential.connector_slug == connector_slug
        )
    ).scalar_one_or_none()

    if cred is None:
        cred = ConnectorCredential(connector_slug=connector_slug)
        db.session.add(cred)

    cred.display_name = display_name or connector_slug
    cred.username = encrypt(username)
    cred.password = encrypt(password)
    cred.extra_config = encrypt_dict(extra or {})
    cred.active = True
    db.session.commit()
    return cred


def load_credentials(connector_slug: str) -> dict[str, Any] | None:
    """
    Load and decrypt credentials for a connector.
    Returns None if not configured.
    """
    from app.extensions import db
    from app.models.connector import ConnectorCredential

    cred = db.session.execute(
        db.select(ConnectorCredential).where(
            ConnectorCredential.connector_slug == connector_slug,
            ConnectorCredential.active == True,
        )
    ).scalar_one_or_none()

    if cred is None or not cred.username:
        return None

    return {
        "username": decrypt(cred.username),
        "password": decrypt(cred.password),
        "extra": decrypt_dict(cred.extra_config) if cred.extra_config else {},
    }


def delete_credentials(connector_slug: str) -> bool:
    """Remove credentials (soft-delete via active=False)."""
    from app.extensions import db
    from app.models.connector import ConnectorCredential

    cred = db.session.execute(
        db.select(ConnectorCredential).where(
            ConnectorCredential.connector_slug == connector_slug
        )
    ).scalar_one_or_none()

    if cred:
        cred.active = False
        cred.username = ""
        cred.password = ""
        cred.extra_config = ""
        db.session.commit()
        return True
    return False
