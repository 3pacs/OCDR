"""
Aggregate all v1 routers into one APIRouter.
"""
from fastapi import APIRouter

from app.api.v1.endpoints import (
    auth,
    patients,
    insurance,
    appointments,
    scans,
    claims,
    payments,
    eobs,
    reconciliation,
    reports,
)

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(auth.router)
api_router.include_router(patients.router)
api_router.include_router(insurance.router)
api_router.include_router(appointments.router)
api_router.include_router(scans.router)
api_router.include_router(claims.router)
api_router.include_router(payments.router)
api_router.include_router(eobs.router)
api_router.include_router(reconciliation.router)
api_router.include_router(reports.router)
