"""API routes for revenue features (F-04, F-05, F-06, F-07)."""

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.revenue.underpayment_detector import get_underpayments, get_underpayment_summary
from backend.app.revenue.filing_deadlines import get_filing_deadlines, get_filing_deadline_alerts
from backend.app.revenue.denial_tracker import (
    get_denials, get_denial_queue, get_denial_summary,
    appeal_denial, resolve_denial, bulk_appeal,
)
from backend.app.revenue.secondary_followup import (
    get_secondary_followup, get_secondary_summary,
    mark_followup, bulk_mark_followup,
)

router = APIRouter()


# --- F-04: Denial Tracking & Appeal Queue ---

@router.get("/denials")
async def denials(
    status: str | None = None,
    carrier: str | None = None,
    modality: str | None = None,
    sort_by: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List all denied claims (F-04)."""
    return await get_denials(db, status, carrier, modality, sort_by, page, per_page)


@router.get("/denials/queue")
async def denial_queue(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Priority appeal queue sorted by recoverability score (F-04)."""
    return await get_denial_queue(db, limit)


@router.get("/denials/summary")
async def denial_summary(db: AsyncSession = Depends(get_db)):
    """Denial summary statistics (F-04)."""
    return await get_denial_summary(db)


class AppealRequest(BaseModel):
    notes: str | None = None
    appeal_date: str | None = None


@router.post("/denials/{billing_id}/appeal")
async def appeal(
    billing_id: int,
    body: AppealRequest,
    db: AsyncSession = Depends(get_db),
):
    """Mark a denied claim as appealed (F-04)."""
    return await appeal_denial(db, billing_id, body.notes, body.appeal_date)


class ResolveRequest(BaseModel):
    resolution: str
    amount: float | None = None


@router.post("/denials/{billing_id}/resolve")
async def resolve(
    billing_id: int,
    body: ResolveRequest,
    db: AsyncSession = Depends(get_db),
):
    """Resolve a denial (F-04)."""
    return await resolve_denial(db, billing_id, body.resolution, body.amount)


class BulkAppealRequest(BaseModel):
    ids: list[int]
    notes: str | None = None


@router.post("/denials/bulk-appeal")
async def bulk_appeal_route(
    body: BulkAppealRequest,
    db: AsyncSession = Depends(get_db),
):
    """Bulk mark claims as appealed (F-04)."""
    return await bulk_appeal(db, body.ids, body.notes)


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


# --- F-07: Secondary Insurance Follow-Up ---

@router.get("/secondary-followup")
async def secondary_followup(
    carrier: str | None = None,
    status: str | None = None,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """List claims missing expected secondary payment (F-07)."""
    return await get_secondary_followup(db, carrier, status, page, per_page)


@router.get("/secondary-followup/summary")
async def secondary_followup_summary(db: AsyncSession = Depends(get_db)):
    """Secondary follow-up summary statistics (F-07)."""
    return await get_secondary_summary(db)


class MarkFollowupRequest(BaseModel):
    status: str
    notes: str | None = None


@router.post("/secondary-followup/{billing_id}/mark")
async def mark_secondary(
    billing_id: int,
    body: MarkFollowupRequest,
    db: AsyncSession = Depends(get_db),
):
    """Mark a claim's secondary follow-up status (F-07)."""
    return await mark_followup(db, billing_id, body.status, body.notes)


class BulkFollowupRequest(BaseModel):
    ids: list[int]
    status: str


@router.post("/secondary-followup/bulk-mark")
async def bulk_mark_secondary(
    body: BulkFollowupRequest,
    db: AsyncSession = Depends(get_db),
):
    """Bulk mark secondary follow-up status (F-07)."""
    return await bulk_mark_followup(db, body.ids, body.status)
