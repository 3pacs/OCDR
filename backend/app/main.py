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

    # Run each migration step in its own transaction so one failure doesn't
    # abort all subsequent operations (PostgreSQL rejects all commands in an
    # aborted transaction).

    # Add missing columns — each in its own transaction
    new_columns = [
        ("billing_records", "import_file_id", "INTEGER"),
        ("billing_records", "extra_data", "JSONB"),
        ("billing_records", "topaz_id", "VARCHAR(50)"),
        ("business_tasks", "action_steps", "TEXT"),
    ]
    for table, column, col_type in new_columns:
        try:
            async with engine.begin() as conn:
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
            async with engine.begin() as conn:
                await conn.execute(text(
                    f"ALTER TABLE {table} ALTER COLUMN {column} TYPE {col_type}"
                ))
        except Exception as e:
            logger.debug(f"Column {table}.{column} widen skipped: {e}")

    # Drop old non-negative payment constraints (refunds/adjustments are legitimate)
    for old_ck in ["ck_billing_primary_nonneg", "ck_billing_secondary_nonneg", "ck_billing_total_nonneg"]:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(
                    f"ALTER TABLE billing_records DROP CONSTRAINT IF EXISTS {old_ck}"
                ))
        except Exception:
            pass

    # Add check constraints (idempotent — skip if already exists)
    constraints = [
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
            async with engine.begin() as conn:
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
            async with engine.begin() as conn:
                await conn.execute(text(sql))
        except Exception as e:
            logger.debug(f"Index skipped: {e}")

    # Backfill: carrier "X" = WRITTEN_OFF (OCMRI convention)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(text(
                "UPDATE billing_records SET denial_status = 'WRITTEN_OFF' "
                "WHERE insurance_carrier = 'X' AND (denial_status IS NULL OR denial_status != 'WRITTEN_OFF')"
            ))
            if result.rowcount:
                logger.info(f"Backfill: marked {result.rowcount} carrier-X records as WRITTEN_OFF")
    except Exception as e:
        logger.debug(f"Carrier X backfill skipped: {e}")

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

    async def _refresh_pipeline_suggestions():
        """Background job: refresh pipeline improvement suggestions daily."""
        try:
            async with AsyncSessionLocal() as session:
                from backend.app.analytics.pipeline_suggestions import generate_pipeline_suggestions
                result = await generate_pipeline_suggestions(session)
                logger.info(f"Pipeline suggestions refreshed: {result.get('total', 0)} suggestions")
        except Exception as e:
            logger.error(f"Pipeline suggestions refresh error: {e}")

    async def _check_recurring_tasks():
        """Background job: generate today's task instances from recurring templates."""
        try:
            async with AsyncSessionLocal() as session:
                from backend.app.tasks.task_scheduler import generate_due_tasks
                count = await generate_due_tasks(session)
                logger.info(f"Recurring tasks checked: {count} new instances created")
        except Exception as e:
            logger.error(f"Recurring task check error: {e}")

    async def _run_auto_improvements():
        """Background job: auto-solve pipeline improvements (crosswalk propagation, etc.)."""
        try:
            async with AsyncSessionLocal() as session:
                from backend.app.analytics.auto_improvements import run_auto_improvements
                results = await run_auto_improvements(session)
                for key, val in results.items():
                    logger.info(f"Auto-improve [{key}]: {val.get('description', val)}")
        except Exception as e:
            logger.error(f"Auto-improvement error: {e}")

    # Run server sync every 15 minutes (individual sources have their own intervals)
    scheduler.add_job(_run_server_sync, "interval", minutes=15, id="server_sync")
    # Refresh pipeline suggestions daily at 6 AM
    scheduler.add_job(_refresh_pipeline_suggestions, "cron", hour=6, id="pipeline_suggestions")
    # Run auto-improvements daily at 6:30 AM (after pipeline refresh)
    scheduler.add_job(_run_auto_improvements, "cron", hour=6, minute=30, id="auto_improvements")
    # Check recurring tasks every morning at 7 AM
    scheduler.add_job(_check_recurring_tasks, "cron", hour=7, id="recurring_tasks")
    scheduler.start()
    logger.info("Background scheduler started (sync=15min, pipeline=6AM, auto-improve=6:30AM, tasks=7AM)")

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
from backend.app.api.routes.task_routes import router as task_router

app.include_router(import_router, prefix="/api/import", tags=["import"])
app.include_router(era_router, prefix="/api/era", tags=["era"])
app.include_router(revenue_router, prefix="/api", tags=["revenue"])
app.include_router(admin_router, prefix="/api", tags=["admin"])
app.include_router(matching_router, prefix="/api/matching", tags=["matching"])
app.include_router(insights_router, prefix="/api/insights", tags=["insights"])
app.include_router(analytics_router, prefix="/api/analytics", tags=["analytics"])
app.include_router(task_router, prefix="/api/tasks", tags=["tasks"])
