"""
Application configuration via pydantic-settings.
All settings are loaded from environment variables / .env file.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional

from pydantic import AnyUrl, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ─────────────────────────────────────────────────────────
    APP_ENV: str = "development"
    APP_HOST: str = "0.0.0.0"
    APP_PORT: int = 8000
    APP_DEBUG: bool = False
    APP_NAME: str = "OCDR Medical Imaging Management System"
    APP_VERSION: str = "1.0.0"
    APP_SECRET_KEY: str = "change-me-in-production"
    APP_ALLOWED_ORIGINS: str = "http://localhost:3000,http://localhost:8000"

    @property
    def allowed_origins_list(self) -> List[str]:
        return [o.strip() for o in self.APP_ALLOWED_ORIGINS.split(",") if o.strip()]

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./ocdr.db"
    DATABASE_ECHO: bool = False

    # ── Encryption ───────────────────────────────────────────────────────────
    ENCRYPTION_KEY: str = ""  # Must be set in production

    # ── JWT ──────────────────────────────────────────────────────────────────
    JWT_SECRET_KEY: str = "change-me-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    SESSION_IDLE_TIMEOUT_MINUTES: int = 15

    # ── Redis / Celery ───────────────────────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/0"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/1"

    # ── Document Watcher Paths ────────────────────────────────────────────────
    WATCH_SCHEDULES_DIR: str = "/data/schedules"
    WATCH_EOBS_DIR: str = "/data/eobs"
    WATCH_PAYMENTS_DIR: str = "/data/payments"
    BACKUP_DIR: str = "/data/backups"

    # ── Matching Thresholds ───────────────────────────────────────────────────
    PATIENT_FUZZY_MATCH_THRESHOLD: int = 85
    PATIENT_REVIEW_THRESHOLD: int = 95
    EOB_AUTO_POST_THRESHOLD: int = 92
    PAYER_TEMPLATE_MIN_EXTRACTIONS: int = 10

    # ── Office Ally ───────────────────────────────────────────────────────────
    OFFICE_ALLY_BASE_URL: str = "https://oa.officeally.com"
    OFFICE_ALLY_USERNAME: Optional[str] = None
    OFFICE_ALLY_PASSWORD: Optional[str] = None
    OFFICE_ALLY_SUBMITTER_ID: Optional[str] = None
    OFFICE_ALLY_SYNC_INTERVAL_HOURS: int = 4

    # ── Microsoft Purview ─────────────────────────────────────────────────────
    PURVIEW_ENABLED: bool = False
    PURVIEW_ENDPOINT: Optional[str] = None
    PURVIEW_TENANT_ID: Optional[str] = None
    PURVIEW_CLIENT_ID: Optional[str] = None
    PURVIEW_CLIENT_SECRET: Optional[str] = None
    PURVIEW_COLLECTION: str = "ocdr-phi-assets"

    # ── Backup ────────────────────────────────────────────────────────────────
    BACKUP_ENABLED: bool = True
    BACKUP_CRON: str = "0 2 * * *"
    BACKUP_RETENTION_DAYS: int = 30

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_FORMAT: str = "json"

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
