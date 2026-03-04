"""OCMRI Billing Reconciliation & Practice Management System."""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.app.core.config import settings


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown events."""
    # Startup: initialize DB connections, start folder watchers
    # TODO: Step 2 - Initialize database / run migrations
    # TODO: Step 12 - Start APScheduler folder watchers
    yield
    # Shutdown: cleanup
    # TODO: Close DuckDB connections, stop scheduler


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
    return {"status": "healthy", "service": "ocmri-billing"}


# --- API Router Registration ---
# TODO: Step 7 - Register route modules:
# from backend.app.api.routes import (
#     patients, studies, payments, crosswalk, ingestion,
#     reconciliation, reports, admin, auth
# )
# app.include_router(patients.router, prefix="/api/patients", tags=["patients"])
# app.include_router(studies.router, prefix="/api/studies", tags=["studies"])
# app.include_router(payments.router, prefix="/api/payments", tags=["payments"])
# app.include_router(crosswalk.router, prefix="/api/crosswalk", tags=["crosswalk"])
# app.include_router(ingestion.router, prefix="/api/ingestion", tags=["ingestion"])
# app.include_router(reconciliation.router, prefix="/api/reconciliation", tags=["reconciliation"])
# app.include_router(reports.router, prefix="/api/reports", tags=["reports"])
# app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
# app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
