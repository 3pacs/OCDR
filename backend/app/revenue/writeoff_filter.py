"""Centralized write-off / terminal claim filter.

A claim is considered "written off" (terminal, not actionable) when ANY of:
  1. denial_status IN ('WRITTEN_OFF', 'RESOLVED', 'PAID_ON_APPEAL')
  2. insurance_carrier = 'X'  (OCMRI convention: X = written off)

All dashboard queries, summary endpoints, and actionable views MUST use
these filters to exclude terminal claims. Import code should also
auto-set denial_status = 'WRITTEN_OFF' when carrier = 'X'.

Usage:
    from backend.app.revenue.writeoff_filter import not_written_off, is_written_off

    # Exclude written-off claims from a query:
    query = select(BillingRecord).where(not_written_off())

    # Find only written-off claims:
    query = select(BillingRecord).where(is_written_off())
"""

from sqlalchemy import or_, and_

from backend.app.models.billing import BillingRecord

# Terminal denial statuses — these claims need no further action
TERMINAL_STATUSES = ("WRITTEN_OFF", "RESOLVED", "PAID_ON_APPEAL")

# Carrier values that indicate write-off (OCMRI convention)
WRITEOFF_CARRIERS = ("X",)


def is_written_off():
    """SQLAlchemy filter: claim IS written off / terminal."""
    return or_(
        BillingRecord.denial_status.in_(TERMINAL_STATUSES),
        BillingRecord.insurance_carrier.in_(WRITEOFF_CARRIERS),
    )


def not_written_off():
    """SQLAlchemy filter: claim is NOT written off — still actionable."""
    return and_(
        or_(
            BillingRecord.denial_status.is_(None),
            ~BillingRecord.denial_status.in_(TERMINAL_STATUSES),
        ),
        ~BillingRecord.insurance_carrier.in_(WRITEOFF_CARRIERS),
    )
