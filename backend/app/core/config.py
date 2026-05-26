"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Compose helpers
    POSTGRES_DB: str = "ocmri"
    POSTGRES_USER: str = "ocmri"
    POSTGRES_PASSWORD: str = "ocmri_secret"
    POSTGRES_PORT: int = 5432

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

    # Browser-assisted payer portal downloads
    OCDR_PORTAL_URLS: str = (
        "https://www.officeally.com/Logout.aspx?Timeout=1;"
        "https://x02.officeally.com/auth0bridge/Logon?ReturnUrl=/secure_oa.asp;"
        "https://myservices.optumhealthpaymentservices.com/registrationSignIn.do;"
        "https://identity.onehealthcareid.com/oneapp/index.html#/login"
    )
    OCDR_PORTAL_DOWNLOAD_DIR: str = "/app/data/portal-downloads"
    OCDR_PORTAL_STAGING_DIR: str = "/app/data/portal-staging"
    OCDR_PORTAL_STATE_DIR: str = "/app/data/portal-state"
    OCDR_PORTAL_DOWNLOAD_EXTENSIONS: str = ".835,.edi,.txt,.dat,.era,.pdf,.csv,.xlsx,.xls,.zip"
    OCDR_PORTAL_MIN_AGE_SECONDS: int = 15
    OCDR_PORTAL_MAX_AGE_HOURS: int = 72
    OCDR_OFFICEALLY_RESET_DELAY_SECONDS: int = 2
    OCDR_SCANSNAP_HOST: str = "ocr-node"
    OCDR_SCANSNAP_STATUS_TIMEOUT_SECONDS: int = 8

    model_config = {"env_file": ".env", "case_sensitive": True, "extra": "ignore"}


settings = Settings()
