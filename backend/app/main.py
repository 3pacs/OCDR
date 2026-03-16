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
        # Add check constraints (idempotent — skip if already exists)
        constraints = [
            "ALTER TABLE billing_records ADD CONSTRAINT ck_billing_primary_nonneg CHECK (primary_payment >= 0)",
            "ALTER TABLE billing_records ADD CONSTRAINT ck_billing_secondary_nonneg CHECK (secondary_payment >= 0)",
            "ALTER TABLE billing_records ADD CONSTRAINT ck_billing_total_nonneg CHECK (total_payment >= 0)",
            "ALTER TABLE billing_records ADD CONSTRAINT ck_billing_patient_name_len CHECK (length(patient_name) >= 2)",
            "ALTER TABLE billing_records ADD CONSTRAINT ck_billing_carrier_len CHECK (length(insurance_carrier) >= 1)",
            "ALTER TABLE billing_records ADD CONSTRAINT ck_billing_modality_len CHECK (length(modality) >= 1)",
            "ALTER TABLE billing_records ADD CONSTRAINT ck_billing_date_min CHECK (service_date >= '2010-01-01')",
            "ALTER TABLE payers ADD CONSTRAINT ck_payer_deadline_positive CHECK (filing_deadline_days > 0)",
            "ALTER TABLE fee_schedule ADD CONSTRAINT ck_fee_rate_positive CHECK (expected_rate > 0)",
            "ALTER TABLE era_claim_lines ADD CONSTRAINT ck_era_claim_status CHECK (claim_status IS NULL OR claim_status IN ('1','2','4','22','23'))",
            "ALTER TABLE era_claim_lines ADD CONSTRAINT ck_era_cas_group CHECK (cas_group_code IS NULL OR cas_group_code IN ('CO','CR','OA','PI','PR'))",
            "ALTER TABLE era_claim_lines ADD CONSTRAINT ck_era_confidence_range CHECK (match_confidence IS NULL OR (match_confidence >= 0 AND match_confidence <= 1))",
        ]
        for sql in constraints:
            try:
                await conn.execute(text(sql))
            except Exception:
                pass  # Constraint already exists

        # Composite indexes for analytics performance
        indexes = [
            "CREATE INDEX IF NOT EXISTS ix_billing_carrier_modality ON billing_records (insurance_carrier, modality)",
            "CREATE INDEX IF NOT EXISTS ix_billing_carrier_payment ON billing_records (insurance_carrier, total_payment)",
            "CREATE INDEX IF NOT EXISTS ix_billing_denial_lookup ON billing_records (denial_status, appeal_deadline)",
            "CREATE INDEX IF NOT EXISTS ix_billing_doctor_carrier ON billing_records (referring_doctor, insurance_carrier)",
            "CREATE INDEX IF NOT EXISTS ix_billing_service_year ON billing_records (service_year, insurance_carrier)",
            "CREATE INDEX IF NOT EXISTS ix_era_claim_match ON era_claim_lines (patient_name_835, service_date_835)",
            "CREATE INDEX IF NOT EXISTS ix_era_claim_status_group ON era_claim_lines (claim_status, cas_group_code)",
        ]
        for sql in indexes:
            try:
                await conn.execute(text(sql))
            except Exception as e:
                logger.debug(f"Index skipped: {e}")

    logger.info("Schema migrations + constraints applied")

    # Seed data on startup
    async with AsyncSessionLocal() as session:
        from backend.app.db.seed_data import run_all_seeds
        result = await run_all_seeds(session)
        logger.info(f"Seed data: {result}")

    # Start background server sync scheduler
    import asyncio
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from backend.app.tasks.server_sync import sync_all_sources

    scheduler = AsyncIOScheduler()

    async def _run_server_sync():
        """Background job: sync all enabled server sources."""
        try:
            async with AsyncSessionLocal() as session:
                results = await sync_all_sources(session)
                for r in results:
                    if "error" in r:
                        logger.warning(f"Server sync error for '{r['name']}': {r['error']}")
                    else:
                        logger.info(f"Server sync '{r['name']}': {r['result']}")
        except Exception as e:
            logger.error(f"Server sync scheduler error: {e}")

    # Run server sync every 15 minutes (individual sources have their own intervals)
    scheduler.add_job(_run_server_sync, "interval", minutes=15, id="server_sync")
    scheduler.start()
    logger.info("Background server sync scheduler started (every 15 min)")

    yield

    # Shutdown
    scheduler.shutdown(wait=False)
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
from backend.app.api.routes.analytics_routes import router as analytics_router

app.include_router(import_router, prefix="/api/import", tags=["import"])
app.include_router(era_router, prefix="/api/era", tags=["era"])
app.include_router(revenue_router, prefix="/api", tags=["revenue"])
app.include_router(admin_router, prefix="/api", tags=["admin"])
app.include_router(matching_router, prefix="/api/matching", tags=["matching"])
app.include_router(insights_router, prefix="/api/insights", tags=["insights"])
app.include_router(analytics_router, prefix="/api/analytics", tags=["analytics"])
