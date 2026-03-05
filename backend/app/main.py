"""OCMRI Billing Reconciliation & Practice Management System."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from backend.app.core.config import settings
from backend.app.db.session import engine, AsyncSessionLocal, Base

# Import models so they register with Base.metadata
import backend.app.models  # noqa: F401

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # Create all tables
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables created/verified")

    # Add columns that may be missing on older databases + widen narrow columns
    async with engine.begin() as conn:
        # Add missing columns
        new_columns = [
            ("billing_records", "import_file_id", "INTEGER"),
            ("billing_records", "extra_data", "JSONB"),
            ("billing_records", "topaz_id", "VARCHAR(50)"),
        ]
        for table, column, col_type in new_columns:
            try:
                await conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {column} {col_type}"
                ))
            except Exception as e:
                logger.debug(f"Column {table}.{column} add skipped: {e}")

        # Widen columns that are too narrow for messy data
        widen_columns = [
            ("billing_records", "scan_type", "VARCHAR(200)"),
            ("billing_records", "insurance_carrier", "VARCHAR(200)"),
            ("billing_records", "modality", "VARCHAR(100)"),
            ("billing_records", "modality_code", "VARCHAR(100)"),
            ("billing_records", "service_month", "VARCHAR(20)"),
            ("billing_records", "service_year", "VARCHAR(10)"),
            ("billing_records", "denial_status", "VARCHAR(50)"),
            ("billing_records", "denial_reason_code", "VARCHAR(50)"),
            ("billing_records", "import_source", "VARCHAR(50)"),
        ]
        for table, column, col_type in widen_columns:
            try:
                await conn.execute(text(
                    f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {col_type}"
                ))
            except Exception as e:
                logger.debug(f"Column {table}.{column} widen skipped: {e}")
    logger.info("Schema migrations applied")

    # Seed data on startup
    async with AsyncSessionLocal() as session:
        from backend.app.db.seed_data import run_all_seeds
        result = await run_all_seeds(session)
        logger.info(f"Seed data: {result}")

    yield

    # Shutdown
    await engine.dispose()


app = FastAPI(
    title="OCMRI Billing Reconciliation",
    description="Billing reconciliation and practice management for OCMRI medical imaging",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS - allow React frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        f"http://localhost:{settings.FRONTEND_PORT}",
        "http://localhost:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
async def health_check():
    """Health check with DB stats."""
    try:
        async with AsyncSessionLocal() as session:
            result = await session.execute(text("SELECT COUNT(*) FROM billing_records"))
            record_count = result.scalar()
    except Exception:
        record_count = 0

    return {
        "status": "healthy",
        "service": "ocmri-billing",
        "record_count": record_count,
    }


# --- API Router Registration ---
from backend.app.api.routes.import_routes import router as import_router
from backend.app.api.routes.era_routes import router as era_router
from backend.app.api.routes.revenue_routes import router as revenue_router
from backend.app.api.routes.admin_routes import router as admin_router
from backend.app.api.routes.matching_routes import router as matching_router
from backend.app.api.routes.insights_routes import router as insights_router

app.include_router(import_router, prefix="/api/import", tags=["import"])
app.include_router(era_router, prefix="/api/era", tags=["era"])
app.include_router(revenue_router, prefix="/api", tags=["revenue"])
app.include_router(admin_router, prefix="/api", tags=["admin"])
app.include_router(matching_router, prefix="/api/matching", tags=["matching"])
app.include_router(insights_router, prefix="/api/insights", tags=["insights"])
