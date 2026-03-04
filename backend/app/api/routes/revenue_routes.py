"""API routes for revenue features (F-05, F-06)."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.revenue.underpayment_detector import get_underpayments, get_underpayment_summary
from backend.app.revenue.filing_deadlines import get_filing_deadlines, get_filing_deadline_alerts

router = APIRouter()


# --- F-05: Underpayments ---

@router.get("/underpayments")
async def underpayments(
    carrier: str | None = None,
    modality: str | None = None,
    threshold: float | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List underpaid claims (F-05)."""
    return await get_underpayments(db, carrier, modality, threshold, page, per_page)


@router.get("/underpayments/summary")
async def underpayments_summary(db: AsyncSession = Depends(get_db)):
    """Underpayment summary statistics (F-05)."""
    return await get_underpayment_summary(db)


# --- F-06: Filing Deadlines ---

@router.get("/filing-deadlines")
async def filing_deadlines(
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List filing deadline statuses (F-06)."""
    return await get_filing_deadlines(db, status, page, per_page)


@router.get("/filing-deadlines/alerts")
async def filing_deadline_alerts(db: AsyncSession = Depends(get_db)):
    """Active filing deadline alerts only (F-06)."""
    return await get_filing_deadline_alerts(db)
