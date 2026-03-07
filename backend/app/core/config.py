"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Database
    DATABASE_URL: str = "postgresql+asyncpg://ocmri:ocmri_secret@localhost:5432/ocmri"
    DATABASE_URL_SYNC: str = "postgresql://ocmri:ocmri_secret@localhost:5432/ocmri"
    DUCKDB_PATH: str = "/app/data/duckdb/analytics.duckdb"

    # Data directories
    DATA_DIR: str = "/app/data"
    EXCEL_DIR: str = "/app/data/excel"
    EOBS_DIR: str = "/app/data/eobs"
    SCHEDULES_DIR: str = "/app/data/schedules"
    PAYMENTS_DIR: str = "/app/data/payments"
    PROCESSED_DIR: str = "/app/data/processed"

    # Auth
    SECRET_KEY: str = "change-me-in-production"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480  # 8 hour sessions
    ALGORITHM: str = "HS256"

    # App
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "info"
    FRONTEND_PORT: int = 3000
    BACKEND_PORT: int = 8000

    # Matching thresholds
    FUZZY_MATCH_THRESHOLD: int = 85
    AUTO_ACCEPT_CONFIDENCE: int = 95
    REVIEW_CONFIDENCE_MIN: int = 75
    MANUAL_CONFIRM_CONFIDENCE_MIN: int = 50

    model_config = {"env_file": ".env", "case_sensitive": True}


settings = Settings()
