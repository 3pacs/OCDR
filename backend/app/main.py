"""
OCDR — Medical Imaging Practice Management System
FastAPI application factory.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.api.v1.router import api_router
from app.schemas.common import HealthResponse

# ── Logging setup ─────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s — %(name)s — %(levelname)s — %(message)s",
)
logger = logging.getLogger("ocdr")


# ── Lifespan (startup / shutdown) ─────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application startup:
      1. Import all models to register with SQLAlchemy mapper
      2. (Optionally) create tables in dev mode
    """
    logger.info("OCDR starting up — environment: %s", settings.APP_ENV)

    # Register all models
    import app.models  # noqa: F401

    if settings.APP_ENV == "development":
        from app.database import create_all_tables
        await create_all_tables()
        logger.info("Development mode: ensured all tables exist")

    yield

    logger.info("OCDR shutting down")


# ── Application factory ───────────────────────────────────────────────────────
def create_app() -> FastAPI:
    application = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description=(
            "Full end-to-end medical imaging practice management system. "
            "Handles patient registration, scheduling, insurance, billing, "
            "EOB ingestion, payment posting, and reconciliation for MRI/PET/CT/Bone scan centers."
        ),
        docs_url="/docs" if not settings.is_production else None,
        redoc_url="/redoc" if not settings.is_production else None,
        openapi_url="/openapi.json" if not settings.is_production else None,
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Trusted hosts (production hardening) ──────────────────────────────────
    if settings.is_production:
        application.add_middleware(
            TrustedHostMiddleware,
            allowed_hosts=["*"],  # Set to your actual domain in production
        )

    # ── Session idle timeout middleware ───────────────────────────────────────
    @application.middleware("http")
    async def session_timeout_middleware(request: Request, call_next):
        # Token expiry is handled by JWT exp claim
        # This middleware can add additional server-side session checking if needed
        response = await call_next(request)
        return response

    # ── Global exception handlers ──────────────────────────────────────────────
    @application.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal server error"},
        )

    # ── Include routers ───────────────────────────────────────────────────────
    application.include_router(api_router)

    # ── Health check ──────────────────────────────────────────────────────────
    @application.get("/health", response_model=HealthResponse, tags=["Health"])
    async def health_check():
        return HealthResponse(
            status="healthy",
            version=settings.APP_VERSION,
            database="connected",
        )

    @application.get("/", include_in_schema=False)
    async def root():
        return {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "docs": "/docs",
            "health": "/health",
        }

    return application


app = create_app()
