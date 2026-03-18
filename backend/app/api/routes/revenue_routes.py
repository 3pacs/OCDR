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
from backend.app.revenue.writeoff_filter import not_written_off
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

    # --- Load denied billing records with ERA billed amounts ---
    # Join with ERA claim lines to get actual billed_amount (not total_payment
    # which is $0 for most denials). Use outerjoin so denials without ERA still appear.
    denied_q = (
        select(BillingRecord)
        .where(BillingRecord.denial_status.is_not(None))
        .where(not_written_off())
    )
    denied_result = await db.execute(denied_q)
    denied_records = denied_result.scalars().all()

    # Batch-fetch ERA billed amounts for matched denied claims
    era_claim_ids = [r.era_claim_id for r in denied_records if r.era_claim_id]
    era_billed_map: dict[str, float] = {}
    if era_claim_ids:
        era_q = select(ERAClaimLine.claim_id, ERAClaimLine.billed_amount).where(
            ERAClaimLine.claim_id.in_(era_claim_ids)
        )
        era_result = await db.execute(era_q)
        for claim_id, billed_amt in era_result.all():
            era_billed_map[claim_id] = float(billed_amt or 0)

    # Load fee schedule for fallback billed amount estimation
    from backend.app.models.payer import FeeSchedule
    fee_result = await db.execute(select(FeeSchedule))
    fee_rates: dict[tuple[str, str], float] = {}  # (carrier, modality) → rate
    fee_defaults: dict[str, float] = {}  # modality → DEFAULT rate
    for f in fee_result.scalars().all():
        if f.cpt_code:
            continue  # Use modality-level rates for estimation
        if f.payer_code == "DEFAULT":
            fee_defaults[f.modality] = float(f.expected_rate)
        else:
            fee_rates[(f.payer_code, f.modality)] = float(f.expected_rate)

    def _get_billed(rec: BillingRecord) -> float:
        """Get billed amount: ERA billed_amount → fee schedule estimate → 0.

        IMPORTANT: Do NOT use extra_charges as fallback — that field is
        miscellaneous charges from OCMRI column K, not the billed amount.
        Using it inflated the collectable amount by millions.
        """
        if rec.era_claim_id and rec.era_claim_id in era_billed_map:
            return era_billed_map[rec.era_claim_id]
        # Fallback: estimate from fee schedule (carrier-specific, then DEFAULT)
        key = (rec.insurance_carrier, rec.modality)
        if key in fee_rates:
            return fee_rates[key]
        if rec.modality in fee_defaults:
            return fee_defaults[rec.modality]
        return 0

    # --- Denial action breakdown ---
    action_buckets: dict[str, dict] = {}
    for rec in denied_records:
        carc = rec.denial_reason_code
        billed = _get_billed(rec)
        paid = float(rec.total_payment or 0)
        detail = get_denial_detail(carc, billed_amount=billed, paid_amount=paid)
        action = detail["recommended_action"]
        bucket = action_buckets.setdefault(action, {
            "action": action,
            "count": 0,
            "total_billed": 0,
            "total_paid": 0,
            "potential_recovery": 0,
            "top_codes": {},
        })
        bucket["count"] += 1
        bucket["total_billed"] += billed
        bucket["total_paid"] += paid
        bucket["potential_recovery"] += detail["financial_context"]["potential_recovery"]
        # Track top CARC codes
        code_key = carc or "UNKNOWN"
        if code_key not in bucket["top_codes"]:
            bucket["top_codes"][code_key] = {
                "carc_code": carc,
                "description": detail["carc_description"],
                "count": 0,
                "fix": detail["fix_instructions"],
            }
        bucket["top_codes"][code_key]["count"] += 1

    # Convert top_codes from dict to sorted list
    for bucket in action_buckets.values():
        codes = list(bucket["top_codes"].values())
        codes.sort(key=lambda x: x["count"], reverse=True)
        bucket["top_codes"] = codes[:5]

    # --- Top recoverable claims ---
    top_claims = []
    for rec in denied_records:
        billed = _get_billed(rec)
        if billed <= 0:
            continue
        paid = float(rec.total_payment or 0)
        detail = get_denial_detail(
            rec.denial_reason_code,
            billed_amount=billed,
            paid_amount=paid,
        )
        if not detail.get("recoverable"):
            continue
        top_claims.append({
            "billing_id": rec.id,
            "patient_name": rec.patient_name,
            "billed_amount": billed,
            "total_payment": paid,
            "potential_recovery": detail["financial_context"]["potential_recovery"],
            "denial_reason_code": rec.denial_reason_code,
            "recommended_action": detail["recommended_action"],
            "fix_instructions": detail["fix_instructions"],
            "service_date": rec.service_date.isoformat() if rec.service_date else None,
            "insurance_carrier": rec.insurance_carrier,
            "priority_score": detail["priority_score"],
        })
    top_claims.sort(key=lambda x: x["priority_score"], reverse=True)

    # --- Quick stats ---
    total_denied_count = len(denied_records)
    total_billed_denied_amt = sum(_get_billed(r) for r in denied_records)

    # --- Unmatched ERA claims ---
    unmatched_count = await db.execute(
        select(func.count(ERAClaimLine.id))
        .where(ERAClaimLine.matched_billing_id.is_(None))
    )

    # --- Filing deadline alerts ---
    deadline_alerts = await get_filing_deadline_alerts(db)

    # --- Summaries ---
    underpayment_summary = await get_underpayment_summary(db)
    secondary_summary = await get_secondary_summary(db)

    return {
        "overview": {
            "total_open_denials": total_denied_count,
            "total_denied_amount": round(total_billed_denied_amt, 2),
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
