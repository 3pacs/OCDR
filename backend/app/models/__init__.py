"""
Import all models here so SQLAlchemy mapper is fully configured
before Alembic or any query runs.
"""
from app.models.user import User
from app.models.patient import Patient
from app.models.insurance import Insurance
from app.models.appointment import Appointment
from app.models.scan import Scan
from app.models.claim import Claim
from app.models.payment import Payment
from app.models.eob import EOB, EOBLineItem
from app.models.reconciliation import Reconciliation
from app.models.audit_log import AuditLog
from app.models.learning import (
    Correction,
    PayerTemplate,
    BusinessRule,
    DenialPattern,
    APICallLog,
)

__all__ = [
    "User",
    "Patient",
    "Insurance",
    "Appointment",
    "Scan",
    "Claim",
    "Payment",
    "EOB",
    "EOBLineItem",
    "Reconciliation",
    "AuditLog",
    "Correction",
    "PayerTemplate",
    "BusinessRule",
    "DenialPattern",
    "APICallLog",
]
