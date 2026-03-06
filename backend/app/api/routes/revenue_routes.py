"""API routes for revenue features (F-04, F-05, F-06, F-07) + reconciliation dashboard."""

import csv
import io

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.models.billing import BillingRecord
from backend.app.revenue.underpayment_detector import get_underpayments, get_underpayment_summary
from backend.app.revenue.filing_deadlines import get_filing_deadlines, get_filing_deadline_alerts
from backend.app.revenue.denial_tracker import (
    get_denials, get_denial_queue, get_denial_summary,
    appeal_denial, resolve_denial, bulk_appeal,
    get_denial_full_detail, export_denials,
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


@router.get("/denials/export")
async def export_denials_csv(
    status: str | None = None,
    carrier: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """
    Export all denials as CSV with all relevant data attached.

    Includes: patient info, billing details, CARC code + description,
    recommended action, fix instructions, severity, and priority score.
    """
    rows = await export_denials(db, status, carrier)

    if not rows:
        return StreamingResponse(
            io.StringIO("No denials found"),
            media_type="text/csv",
            headers={"Content-Disposition": "attachment; filename=denials_export.csv"},
        )

    # Define CSV columns
    columns = [
        "id", "patient_name", "patient_id", "topaz_id",
        "service_date", "insurance_carrier", "modality", "scan_type",
        "referring_doctor", "billed_amount", "total_payment",
        "denial_status", "denial_reason_code", "denial_reason_description",
        "cas_group_code", "cas_group_label", "cas_adjustment_amount",
        "recommended_action", "fix_instructions", "severity",
        "recoverable", "priority_score",
        "appeal_deadline", "days_old", "recoverability_score",
        "era_claim_id",
    ]

    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=denials_export.csv"},
    )


@router.get("/denials/{billing_id}/detail")
async def denial_detail(
    billing_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Full denial detail with ERA context, CARC code explanation,
    recommended fix, related claims, and appeal history.

    Click on any denial to see exactly what went wrong and what to do.
    """
    return await get_denial_full_detail(db, billing_id)


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


# --- Reconciliation Dashboard ---

@router.get("/reconciliation/dashboard")
async def reconciliation_dashboard(db: AsyncSession = Depends(get_db)):
    """
    Action-oriented reconciliation dashboard.

    Single endpoint that shows what needs attention right now:
    - Denials requiring action (grouped by recommended action type)
    - Top recoverable claims (highest priority first)
    - Filing deadline alerts
    - Underpayment summary
    - Secondary follow-up status
    - Matching health (unmatched ERA claims)
    """
    from backend.app.models.era import ERAClaimLine
    from backend.app.revenue.denial_actions import get_denial_detail, CARC_ACTION_MAP

    # --- Denial action breakdown ---
    denial_result = await db.execute(
        select(
            BillingRecord.denial_reason_code,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.billed_amount).label("total_billed"),
            func.sum(BillingRecord.total_payment).label("total_paid"),
        )
        .where(BillingRecord.denial_status.is_not(None))
        .where(BillingRecord.denial_status.notin_(["RESOLVED", "WRITTEN_OFF", "PAID_ON_APPEAL"]))
        .group_by(BillingRecord.denial_reason_code)
    )
    denial_rows = denial_result.all()

    action_buckets: dict[str, dict] = {}
    for carc, count, billed, paid in denial_rows:
        detail = get_denial_detail(carc, billed_amount=float(billed or 0))
        action = detail["recommended_action"]
        bucket = action_buckets.setdefault(action, {
            "action": action,
            "count": 0,
            "total_billed": 0,
            "total_paid": 0,
            "potential_recovery": 0,
            "top_codes": [],
        })
        bucket["count"] += count
        bucket["total_billed"] += float(billed or 0)
        bucket["total_paid"] += float(paid or 0)
        bucket["potential_recovery"] += detail["financial_context"]["potential_recovery"]
        bucket["top_codes"].append({
            "carc_code": carc,
            "description": detail["carc_description"],
            "count": count,
            "fix": detail["fix_instructions"],
        })

    # Sort top_codes within each bucket by count
    for bucket in action_buckets.values():
        bucket["top_codes"].sort(key=lambda x: x["count"], reverse=True)
        bucket["top_codes"] = bucket["top_codes"][:5]

    # --- Top recoverable claims ---
    top_recoverable = await db.execute(
        select(
            BillingRecord.id,
            BillingRecord.patient_name,
            BillingRecord.billed_amount,
            BillingRecord.total_payment,
            BillingRecord.denial_reason_code,
            BillingRecord.denial_status,
            BillingRecord.service_date,
            BillingRecord.insurance_carrier,
        )
        .where(BillingRecord.denial_status.is_not(None))
        .where(BillingRecord.denial_status.notin_(["RESOLVED", "WRITTEN_OFF", "PAID_ON_APPEAL"]))
        .where(BillingRecord.billed_amount.is_not(None))
        .order_by(BillingRecord.billed_amount.desc())
        .limit(20)
    )
    top_claims = []
    for row in top_recoverable.all():
        detail = get_denial_detail(
            row.denial_reason_code,
            billed_amount=float(row.billed_amount or 0),
            paid_amount=float(row.total_payment or 0),
        )
        top_claims.append({
            "billing_id": row.id,
            "patient_name": row.patient_name,
            "billed_amount": float(row.billed_amount or 0),
            "total_payment": float(row.total_payment or 0),
            "potential_recovery": detail["financial_context"]["potential_recovery"],
            "denial_reason_code": row.denial_reason_code,
            "recommended_action": detail["recommended_action"],
            "fix_instructions": detail["fix_instructions"],
            "service_date": row.service_date.isoformat() if row.service_date else None,
            "insurance_carrier": row.insurance_carrier,
            "priority_score": detail["priority_score"],
        })
    top_claims.sort(key=lambda x: x["priority_score"], reverse=True)

    # --- Quick stats ---
    total_denied = await db.execute(
        select(func.count(BillingRecord.id))
        .where(BillingRecord.denial_status.is_not(None))
        .where(BillingRecord.denial_status.notin_(["RESOLVED", "WRITTEN_OFF", "PAID_ON_APPEAL"]))
    )
    total_billed_denied = await db.execute(
        select(func.sum(BillingRecord.billed_amount))
        .where(BillingRecord.denial_status.is_not(None))
        .where(BillingRecord.denial_status.notin_(["RESOLVED", "WRITTEN_OFF", "PAID_ON_APPEAL"]))
    )

    # --- Unmatched ERA claims ---
    unmatched_count = await db.execute(
        select(func.count(ERAClaimLine.id))
        .where(ERAClaimLine.billing_record_id.is_(None))
    )

    # --- Filing deadline alerts ---
    deadline_alerts = await get_filing_deadline_alerts(db)

    # --- Summaries ---
    underpayment_summary = await get_underpayment_summary(db)
    secondary_summary = await get_secondary_summary(db)

    return {
        "overview": {
            "total_open_denials": total_denied.scalar() or 0,
            "total_denied_amount": float(total_billed_denied.scalar() or 0),
            "unmatched_era_claims": unmatched_count.scalar() or 0,
        },
        "action_buckets": sorted(
            action_buckets.values(),
            key=lambda x: x["potential_recovery"],
            reverse=True,
        ),
        "top_recoverable_claims": top_claims[:10],
        "filing_deadline_alerts": deadline_alerts,
        "underpayment_summary": underpayment_summary,
        "secondary_followup_summary": secondary_summary,
        "tips": [
            "Start with CORRECT_AND_RESUBMIT claims — these are fixable errors with high recovery potential.",
            "APPEAL claims need supporting documentation. Gather clinical notes before starting.",
            "PATIENT_BILL items are patient responsibility — send statements promptly.",
            "WRITE_OFF items are contractual. Post adjustments to clear your A/R.",
            "Check filing deadlines weekly — missed deadlines = lost revenue permanently.",
            "Unmatched ERA claims may contain payments not yet posted to billing records.",
        ],
    }
