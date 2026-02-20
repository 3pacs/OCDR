"""
JWT creation / verification, password hashing, and RBAC helpers.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings

# ── Password hashing ─────────────────────────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain_password: str) -> str:
    return pwd_context.hash(plain_password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


# ── Token creation ────────────────────────────────────────────────────────────
def create_access_token(subject: Any, extra: Optional[Dict] = None) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload: Dict[str, Any] = {
        "sub": str(subject),
        "exp": expire,
        "type": "access",
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(subject: Any) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS
    )
    payload = {
        "sub": str(subject),
        "exp": expire,
        "type": "refresh",
    }
    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def decode_token(token: str) -> Dict[str, Any]:
    """Decode and verify a JWT. Raises JWTError on failure."""
    return jwt.decode(
        token,
        settings.JWT_SECRET_KEY,
        algorithms=[settings.JWT_ALGORITHM],
    )


# ── Role definitions ──────────────────────────────────────────────────────────
class Role:
    ADMIN = "admin"
    BILLER = "biller"
    FRONT_DESK = "front_desk"
    READ_ONLY = "read_only"

    # Fields hidden from front_desk and read_only roles
    FINANCIAL_RESTRICTED_ROLES = {FRONT_DESK, READ_ONLY}

    @classmethod
    def all_roles(cls):
        return [cls.ADMIN, cls.BILLER, cls.FRONT_DESK, cls.READ_ONLY]


# ── Permission helpers ────────────────────────────────────────────────────────
ROLE_PERMISSIONS: Dict[str, set] = {
    Role.ADMIN: {
        "patients:read", "patients:write", "patients:delete",
        "insurance:read", "insurance:write",
        "appointments:read", "appointments:write",
        "scans:read", "scans:write",
        "claims:read", "claims:write",
        "payments:read", "payments:write",
        "eobs:read", "eobs:write",
        "reconciliation:read", "reconciliation:write",
        "reports:read",
        "admin:read", "admin:write",
        "users:read", "users:write",
    },
    Role.BILLER: {
        "patients:read", "patients:write",
        "insurance:read", "insurance:write",
        "appointments:read",
        "scans:read", "scans:write",
        "claims:read", "claims:write",
        "payments:read", "payments:write",
        "eobs:read", "eobs:write",
        "reconciliation:read", "reconciliation:write",
        "reports:read",
    },
    Role.FRONT_DESK: {
        "patients:read", "patients:write",
        "insurance:read", "insurance:write",
        "appointments:read", "appointments:write",
        "scans:read",
    },
    Role.READ_ONLY: {
        "patients:read",
        "insurance:read",
        "appointments:read",
        "scans:read",
        "reports:read",
    },
}


def has_permission(role: str, permission: str) -> bool:
    return permission in ROLE_PERMISSIONS.get(role, set())


def can_see_financials(role: str) -> bool:
    return role not in Role.FINANCIAL_RESTRICTED_ROLES
