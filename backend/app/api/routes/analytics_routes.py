"""API routes for analytics dashboards (F-08, F-09, F-13, F-14, F-15, F-16).

Covers: Payer Monitor, Physician Analytics, PSMA Tracking, Gado Analytics,
Duplicate Detection, and Denial Reason Analytics.
"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from sqlalchemy import select, func, case, extract, text, and_, or_, cast, String, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.db.session import get_db
from backend.app.models.billing import BillingRecord
from backend.app.models.payer import Payer, FeeSchedule
from backend.app.models.era import ERAClaimLine
from backend.app.models.insight_log import InsightLog

router = APIRouter()


# ---------------------------------------------------------------------------
# Pipeline Improvement Suggestions
# ---------------------------------------------------------------------------

@router.get("/pipeline-suggestions")
async def pipeline_suggestions(db: AsyncSession = Depends(get_db)):
    """Generate pipeline improvement suggestions from billing data analysis."""
    from backend.app.analytics.pipeline_suggestions import (
        generate_pipeline_suggestions,
        persist_pipeline_suggestions,
        BENCHMARKS,
    )
    suggestions = await generate_pipeline_suggestions(db)
    saved = await persist_pipeline_suggestions(db, suggestions)

    # Summary stats
    by_severity = {}
    by_category = {}
    total_impact = 0
    for s in suggestions:
        sev = s.get("severity", "LOW")
        by_severity[sev] = by_severity.get(sev, 0) + 1
        cat = s.get("subcategory", "GENERAL")
        by_category[cat] = by_category.get(cat, 0) + 1
        total_impact += abs(s.get("estimated_impact") or 0)

    # Fetch user notes from persisted insights
    notes_result = await db.execute(
        select(InsightLog.title, InsightLog.status, InsightLog.resolution_notes)
        .where(InsightLog.category.like("PIPELINE_%"))
    )
    notes_map = {
        row[0]: {"status": row[1], "notes": row[2]}
        for row in notes_result.all()
    }

    # Merge notes into suggestions
    for s in suggestions:
        info = notes_map.get(s["title"], {})
        s["user_status"] = info.get("status", "OPEN")
        s["user_notes"] = info.get("notes")

    return {
        "suggestions": suggestions,
        "total": len(suggestions),
        "total_impact": round(total_impact, 2),
        "new_persisted": saved,
        "by_severity": by_severity,
        "by_category": by_category,
        "benchmarks": BENCHMARKS,
        "generated_at": date.today().isoformat(),
    }


class PipelineNoteUpdate(BaseModel):
    title: str
    status: Optional[str] = None  # OPEN, ACKNOWLEDGED, IN_PROGRESS, RESOLVED, DISMISSED
    notes: Optional[str] = None


@router.patch("/pipeline-suggestions/note")
async def update_pipeline_note(body: PipelineNoteUpdate, db: AsyncSession = Depends(get_db)):
    """Add a note or update status on a pipeline suggestion. Written to TASKS.md for LLM access."""
    result = await db.execute(
        select(InsightLog).where(
            and_(
                InsightLog.category.like("PIPELINE_%"),
                InsightLog.title == body.title,
            )
        )
    )
    log = result.scalar_one_or_none()
    if not log:
        raise HTTPException(status_code=404, detail="Pipeline suggestion not found in log")

    if body.status is not None:
        log.status = body.status
        if body.status == "RESOLVED":
            log.resolved_at = datetime.utcnow()
    if body.notes is not None:
        log.resolution_notes = body.notes

    await db.commit()

    # Also regenerate TASKS.md so LLM sees updated pipeline notes
    try:
        from backend.app.tasks.task_log_writer import write_tasks_md
        await write_tasks_md(db)
    except Exception:
        pass

    return {"title": log.title, "status": log.status, "notes": log.resolution_notes}


@router.get("/pipeline-notes")
async def list_pipeline_notes(db: AsyncSession = Depends(get_db)):
    """Get all pipeline suggestion notes/statuses for LLM consumption."""
    result = await db.execute(
        select(InsightLog)
        .where(InsightLog.category.like("PIPELINE_%"))
        .order_by(InsightLog.updated_at.desc())
    )
    logs = result.scalars().all()
    return [
        {
            "id": l.id,
            "title": l.title,
            "category": l.category,
            "severity": l.severity,
            "status": l.status,
            "notes": l.resolution_notes,
            "estimated_impact": float(l.estimated_impact) if l.estimated_impact else None,
            "created_at": l.created_at.isoformat(),
            "updated_at": l.updated_at.isoformat(),
        }
        for l in logs
    ]


# ---------------------------------------------------------------------------
# Daily Review (AI system health check)
# ---------------------------------------------------------------------------

@router.get("/daily-review")
async def daily_review(db: AsyncSession = Depends(get_db)):
    """Run AI daily system review. Returns structured findings and updates TASKS.md."""
    from backend.app.analytics.daily_review import run_daily_review, format_review_markdown
    from backend.app.tasks.task_log_writer import write_tasks_md

    findings = await run_daily_review(db)

    # Also regenerate TASKS.md
    try:
        await write_tasks_md(db)
    except Exception:
        pass

    return findings


@router.post("/auto-improve")
async def auto_improve(db: AsyncSession = Depends(get_db)):
    """Run auto-improvement routines that directly solve pipeline suggestions.

    Currently solves:
    - Crosswalk propagation (fills missing Topaz IDs from same patient's other records)
    - Secondary billing flagging (identifies claims needing secondary)
    - Filing deadline alerting (flags urgent/expired deadlines)
    """
    from backend.app.analytics.auto_improvements import run_auto_improvements
    results = await run_auto_improvements(db)
    return results


# ---------------------------------------------------------------------------
# F-09: Payer Contract Monitor & Alerts
# ---------------------------------------------------------------------------

@router.get("/payer-alerts")
async def payer_alerts(db: AsyncSession = Depends(get_db)):
    """Active payer alerts — carriers with significant revenue or volume drops."""
    # Monthly revenue + volume by carrier for the last 12 months
    twelve_months_ago = date.today() - timedelta(days=365)
    result = await db.execute(
        select(
            BillingRecord.insurance_carrier,
            func.to_char(BillingRecord.service_date, 'YYYY-MM').label("month"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.service_date >= twelve_months_ago)
        .group_by(BillingRecord.insurance_carrier, text("2"))
        .order_by(BillingRecord.insurance_carrier, text("2"))
    )
    rows = result.all()

    # Build per-carrier monthly data
    carrier_months: dict[str, list[dict]] = {}
    for carrier, month, revenue, volume in rows:
        carrier_months.setdefault(carrier, []).append({
            "month": month,
            "revenue": float(revenue or 0),
            "volume": volume,
        })

    # Get payer thresholds
    payer_result = await db.execute(select(Payer.code, Payer.alert_threshold_pct, Payer.display_name))
    payer_map = {r.code: {"threshold": float(r.alert_threshold_pct or 0.25), "name": r.display_name} for r in payer_result.all()}

    alerts = []
    for carrier, months in carrier_months.items():
        if len(months) < 2:
            continue
        # Last month vs avg of prior 3
        sorted_months = sorted(months, key=lambda x: x["month"])
        current = sorted_months[-1]
        prior = sorted_months[-4:-1] if len(sorted_months) >= 4 else sorted_months[:-1]
        if not prior:
            continue
        avg_revenue = sum(m["revenue"] for m in prior) / len(prior)
        avg_volume = sum(m["volume"] for m in prior) / len(prior)

        threshold = payer_map.get(carrier, {}).get("threshold", 0.25)

        rev_drop = (avg_revenue - current["revenue"]) / avg_revenue if avg_revenue > 0 else 0
        vol_drop = (avg_volume - current["volume"]) / avg_volume if avg_volume > 0 else 0

        if rev_drop > threshold or vol_drop > threshold:
            severity = "RED" if rev_drop > 0.5 or vol_drop > 0.5 else "YELLOW"
            alerts.append({
                "carrier": carrier,
                "display_name": payer_map.get(carrier, {}).get("name", carrier),
                "severity": severity,
                "current_month": current["month"],
                "current_revenue": current["revenue"],
                "avg_prior_revenue": round(avg_revenue, 2),
                "revenue_drop_pct": round(rev_drop * 100, 1),
                "current_volume": current["volume"],
                "avg_prior_volume": round(avg_volume, 1),
                "volume_drop_pct": round(vol_drop * 100, 1),
            })

    alerts.sort(key=lambda x: x["revenue_drop_pct"], reverse=True)
    return {"alerts": alerts, "total": len(alerts)}


@router.get("/payer-monitor")
async def payer_monitor(db: AsyncSession = Depends(get_db)):
    """Overview of all payers with revenue trends."""
    result = await db.execute(
        select(
            BillingRecord.insurance_carrier,
            func.sum(BillingRecord.total_payment).label("total_revenue"),
            func.count(BillingRecord.id).label("total_claims"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("zero_pay_count"),
        )
        .group_by(BillingRecord.insurance_carrier)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    carriers = []
    for row in result.all():
        carriers.append({
            "carrier": row.insurance_carrier,
            "total_revenue": float(row.total_revenue or 0),
            "total_claims": row.total_claims,
            "avg_payment": round(float(row.avg_payment or 0), 2),
            "zero_pay_count": row.zero_pay_count,
            "zero_pay_pct": round(row.zero_pay_count / row.total_claims * 100, 1) if row.total_claims > 0 else 0,
        })
    return {"carriers": carriers}


@router.get("/payer-monitor/{carrier:path}")
async def payer_detail(carrier: str, db: AsyncSession = Depends(get_db)):
    """Monthly breakdown for a specific carrier."""
    result = await db.execute(
        select(
            func.to_char(BillingRecord.service_date, 'YYYY-MM').label("month"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
        )
        .where(BillingRecord.insurance_carrier == carrier)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    monthly = [
        {
            "month": r.month,
            "revenue": float(r.revenue or 0),
            "volume": r.volume,
            "avg_payment": round(float(r.avg_payment or 0), 2),
        }
        for r in result.all()
    ]

    # Modality breakdown
    mod_result = await db.execute(
        select(
            BillingRecord.modality,
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.insurance_carrier == carrier)
        .group_by(BillingRecord.modality)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    by_modality = [
        {"modality": r.modality, "revenue": float(r.revenue or 0), "volume": r.volume}
        for r in mod_result.all()
    ]

    return {"carrier": carrier, "monthly": monthly, "by_modality": by_modality}


# ---------------------------------------------------------------------------
# F-15: Physician Analytics
# ---------------------------------------------------------------------------

@router.get("/physicians")
async def physician_rankings(
    sort_by: str = Query("revenue", enum=["revenue", "volume"]),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Top physicians ranked by revenue or volume."""
    order = func.sum(BillingRecord.total_payment).desc() if sort_by == "revenue" else func.count(BillingRecord.id).desc()
    result = await db.execute(
        select(
            BillingRecord.referring_doctor,
            func.sum(BillingRecord.total_payment).label("total_revenue"),
            func.count(BillingRecord.id).label("total_claims"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
            func.count(func.distinct(BillingRecord.insurance_carrier)).label("carrier_count"),
            func.count(func.distinct(BillingRecord.modality)).label("modality_count"),
        )
        .group_by(BillingRecord.referring_doctor)
        .order_by(order)
        .limit(limit)
    )
    physicians = []
    for r in result.all():
        physicians.append({
            "name": r.referring_doctor,
            "total_revenue": float(r.total_revenue or 0),
            "total_claims": r.total_claims,
            "avg_payment": round(float(r.avg_payment or 0), 2),
            "carrier_count": r.carrier_count,
            "modality_count": r.modality_count,
        })

    # Calculate share percentages
    total_rev = sum(p["total_revenue"] for p in physicians)
    for p in physicians:
        p["revenue_share_pct"] = round(p["total_revenue"] / total_rev * 100, 1) if total_rev > 0 else 0

    return {"physicians": physicians, "total_revenue": total_rev}


@router.get("/physicians/{name:path}")
async def physician_detail(name: str, db: AsyncSession = Depends(get_db)):
    """Detailed breakdown for a specific physician."""
    # By modality
    mod_result = await db.execute(
        select(
            BillingRecord.modality,
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.referring_doctor == name)
        .group_by(BillingRecord.modality)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    by_modality = [
        {"modality": r.modality, "revenue": float(r.revenue or 0), "volume": r.volume}
        for r in mod_result.all()
    ]

    # By carrier
    carrier_result = await db.execute(
        select(
            BillingRecord.insurance_carrier,
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.referring_doctor == name)
        .group_by(BillingRecord.insurance_carrier)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    by_carrier = [
        {"carrier": r.insurance_carrier, "revenue": float(r.revenue or 0), "volume": r.volume}
        for r in carrier_result.all()
    ]

    # Monthly trend
    monthly_result = await db.execute(
        select(
            func.to_char(BillingRecord.service_date, 'YYYY-MM').label("month"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.count(BillingRecord.id).label("volume"),
        )
        .where(BillingRecord.referring_doctor == name)
        .group_by(text("1"))
        .order_by(text("1"))
    )
    monthly = [
        {"month": r.month, "revenue": float(r.revenue or 0), "volume": r.volume}
        for r in monthly_result.all()
    ]

    # Gado usage
    gado_result = await db.execute(
        select(
            func.count(BillingRecord.id).label("total"),
            func.sum(case((BillingRecord.gado_used.is_(True), 1), else_=0)).label("gado_count"),
        )
        .where(BillingRecord.referring_doctor == name)
    )
    gado = gado_result.one()

    return {
        "name": name,
        "by_modality": by_modality,
        "by_carrier": by_carrier,
        "monthly": monthly,
        "total_claims": gado.total,
        "gado_claims": gado.gado_count,
        "gado_pct": round(gado.gado_count / gado.total * 100, 1) if gado.total > 0 else 0,
    }


# ---------------------------------------------------------------------------
# F-13: PSMA PET Tracking
# ---------------------------------------------------------------------------

@router.get("/psma")
async def psma_dashboard(db: AsyncSession = Depends(get_db)):
    """PSMA PET scan tracking — volume, revenue, trends."""
    # Overall PSMA stats
    result = await db.execute(
        select(
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
        )
        .where(BillingRecord.is_psma.is_(True))
    )
    stats = result.one()

    # Standard PET comparison
    std_result = await db.execute(
        select(
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
        )
        .where(BillingRecord.modality == "PET")
        .where(BillingRecord.is_psma.is_(False))
    )
    std_stats = std_result.one()

    # By year
    yearly = await db.execute(
        select(
            BillingRecord.service_year,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.is_psma.is_(True))
        .group_by(BillingRecord.service_year)
        .order_by(BillingRecord.service_year)
    )
    by_year = [
        {"year": r.service_year, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in yearly.all()
    ]

    # By referring doctor
    by_doc = await db.execute(
        select(
            BillingRecord.referring_doctor,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.is_psma.is_(True))
        .group_by(BillingRecord.referring_doctor)
        .order_by(func.sum(BillingRecord.total_payment).desc())
        .limit(10)
    )
    by_physician = [
        {"name": r.referring_doctor, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in by_doc.all()
    ]

    return {
        "psma": {
            "count": stats.count,
            "revenue": float(stats.revenue or 0),
            "avg_payment": round(float(stats.avg_payment or 0), 2),
        },
        "standard_pet": {
            "count": std_stats.count,
            "revenue": float(std_stats.revenue or 0),
            "avg_payment": round(float(std_stats.avg_payment or 0), 2),
        },
        "by_year": by_year,
        "by_physician": by_physician,
    }


# ---------------------------------------------------------------------------
# F-14: Gado Contrast Analytics
# ---------------------------------------------------------------------------

@router.get("/gado")
async def gado_dashboard(
    gado_cost_per_dose: float = Query(50.0, description="Cost per Gado dose"),
    db: AsyncSession = Depends(get_db),
):
    """Gadolinium contrast analytics — volume, revenue, margin."""
    # Overall gado stats
    result = await db.execute(
        select(
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
        )
        .where(BillingRecord.gado_used.is_(True))
    )
    stats = result.one()

    total_cost = stats.count * gado_cost_per_dose
    margin = float(stats.revenue or 0) - total_cost

    # By modality
    by_mod = await db.execute(
        select(
            BillingRecord.modality,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.gado_used.is_(True))
        .group_by(BillingRecord.modality)
        .order_by(func.sum(BillingRecord.total_payment).desc())
    )
    by_modality = [
        {"modality": r.modality, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in by_mod.all()
    ]

    # By year
    by_yr = await db.execute(
        select(
            BillingRecord.service_year,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.gado_used.is_(True))
        .group_by(BillingRecord.service_year)
        .order_by(BillingRecord.service_year)
    )
    by_year = [
        {"year": r.service_year, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in by_yr.all()
    ]

    # Top referring doctors for gado
    by_doc = await db.execute(
        select(
            BillingRecord.referring_doctor,
            func.count(BillingRecord.id).label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.gado_used.is_(True))
        .group_by(BillingRecord.referring_doctor)
        .order_by(func.count(BillingRecord.id).desc())
        .limit(10)
    )
    by_physician = [
        {"name": r.referring_doctor, "count": r.count, "revenue": float(r.revenue or 0)}
        for r in by_doc.all()
    ]

    return {
        "total_claims": stats.count,
        "total_revenue": float(stats.revenue or 0),
        "avg_payment": round(float(stats.avg_payment or 0), 2),
        "cost_per_dose": gado_cost_per_dose,
        "total_cost": total_cost,
        "margin": round(margin, 2),
        "margin_pct": round(margin / float(stats.revenue or 1) * 100, 1),
        "revenue_per_dollar_cost": round(float(stats.revenue or 0) / total_cost, 2) if total_cost > 0 else 0,
        "by_modality": by_modality,
        "by_year": by_year,
        "by_physician": by_physician,
    }


# ---------------------------------------------------------------------------
# F-08: Duplicate Claim Detector
# ---------------------------------------------------------------------------

@router.get("/duplicates")
async def duplicates(
    include_legitimate: bool = Query(False),
    db: AsyncSession = Depends(get_db),
):
    """Detect duplicate claims. Respects C.A.P exception (BR-01)."""
    # Find groups with same patient + date + scan + modality having > 1 record
    dup_query = (
        select(
            BillingRecord.patient_name,
            BillingRecord.service_date,
            BillingRecord.scan_type,
            BillingRecord.modality,
            func.count(BillingRecord.id).label("count"),
            func.array_agg(BillingRecord.id).label("ids"),
            func.array_agg(BillingRecord.description).label("descriptions"),
            func.array_agg(BillingRecord.total_payment).label("payments"),
            func.array_agg(BillingRecord.insurance_carrier).label("carriers"),
        )
        .group_by(
            BillingRecord.patient_name,
            BillingRecord.service_date,
            BillingRecord.scan_type,
            BillingRecord.modality,
        )
        .having(func.count(BillingRecord.id) > 1)
        .order_by(func.count(BillingRecord.id).desc())
    )
    result = await db.execute(dup_query)

    groups = []
    cap_excluded = 0
    for row in result.all():
        descriptions = [str(d or "").upper() for d in row.descriptions]
        is_cap = any("C.A.P" in d or d == "CAP" for d in descriptions)

        if is_cap and not include_legitimate:
            cap_excluded += 1
            continue

        groups.append({
            "patient_name": row.patient_name,
            "service_date": row.service_date.isoformat() if row.service_date else None,
            "scan_type": row.scan_type,
            "modality": row.modality,
            "count": row.count,
            "ids": list(row.ids),
            "descriptions": list(row.descriptions),
            "payments": [float(p or 0) for p in row.payments],
            "carriers": list(row.carriers),
            "is_cap_exception": is_cap,
        })

    return {
        "duplicate_groups": groups,
        "total_groups": len(groups),
        "cap_excluded": cap_excluded,
        "total_duplicate_records": sum(g["count"] for g in groups),
    }


# ---------------------------------------------------------------------------
# F-16: Denial Reason Code Analytics
# ---------------------------------------------------------------------------

@router.get("/denial-analytics")
async def denial_analytics(
    carrier: str | None = None,
    top_n: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Denial reason code analytics — Pareto analysis by frequency and dollar amount."""
    from backend.app.revenue.denial_actions import get_denial_detail

    base = select(
        BillingRecord.denial_reason_code,
        func.count(BillingRecord.id).label("count"),
        func.sum(BillingRecord.total_payment).label("total_paid"),
        BillingRecord.insurance_carrier,
        BillingRecord.modality,
    ).where(BillingRecord.denial_status.is_not(None))

    if carrier:
        base = base.where(BillingRecord.insurance_carrier == carrier)

    # By reason code
    by_reason = await db.execute(
        select(
            BillingRecord.denial_reason_code,
            func.count(BillingRecord.id).label("count"),
        )
        .where(BillingRecord.denial_status.is_not(None))
        .where(BillingRecord.denial_reason_code.is_not(None))
        .group_by(BillingRecord.denial_reason_code)
        .order_by(func.count(BillingRecord.id).desc())
        .limit(top_n)
    )
    reasons = []
    total_denied = 0
    for r in by_reason.all():
        detail = get_denial_detail(r.denial_reason_code)
        total_denied += r.count
        reasons.append({
            "code": r.denial_reason_code,
            "description": detail.get("carc_description", "Unknown"),
            "count": r.count,
            "recommended_action": detail.get("recommended_action", "REVIEW"),
            "recoverable": detail.get("recoverable", False),
        })

    # Cumulative % for Pareto
    running = 0
    for r in reasons:
        running += r["count"]
        r["cumulative_pct"] = round(running / total_denied * 100, 1) if total_denied > 0 else 0

    # By carrier
    by_carrier_result = await db.execute(
        select(
            BillingRecord.insurance_carrier,
            func.count(BillingRecord.id).label("count"),
        )
        .where(BillingRecord.denial_status.is_not(None))
        .group_by(BillingRecord.insurance_carrier)
        .order_by(func.count(BillingRecord.id).desc())
        .limit(10)
    )
    by_carrier = [
        {"carrier": r.insurance_carrier, "count": r.count}
        for r in by_carrier_result.all()
    ]

    # By modality
    by_modality_result = await db.execute(
        select(
            BillingRecord.modality,
            func.count(BillingRecord.id).label("count"),
        )
        .where(BillingRecord.denial_status.is_not(None))
        .group_by(BillingRecord.modality)
        .order_by(func.count(BillingRecord.id).desc())
    )
    by_modality = [
        {"modality": r.modality, "count": r.count}
        for r in by_modality_result.all()
    ]

    return {
        "by_reason": reasons,
        "by_carrier": by_carrier,
        "by_modality": by_modality,
        "total_denied": total_denied,
    }


# ---------------------------------------------------------------------------
# Patient Lookup — search by name, view all visits + payment status
# ---------------------------------------------------------------------------

@router.get("/patients/search")
async def patient_search(
    q: str = Query(..., min_length=2, description="Search by name, chart ID, patient ID, or DOB"),
    limit: int = Query(25, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Search patients by name, patient_id, chart number, topaz_id, or date of birth.

    Smart detection:
      - Digits only → search patient_id (chart number) and topaz_id
      - Date-like (MM/DD/YYYY, YYYY-MM-DD, MM-DD-YYYY) → search birth_date
      - Otherwise → name search (case-insensitive partial match)
    All searches are forgiving: partial matches, no exact spelling required.
    """
    raw = q.strip()

    # --- Detect search type ---
    filters = []

    # Check if it looks like a date (contains / or - with digits)
    parsed_date = None
    if any(c in raw for c in ("/")):
        # Try MM/DD/YYYY, M/D/YYYY
        for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
            try:
                from datetime import datetime as _dt
                parsed_date = _dt.strptime(raw, fmt).date()
                break
            except ValueError:
                continue
    if parsed_date is None and len(raw) == 10 and raw[4] == "-":
        # YYYY-MM-DD
        try:
            from datetime import datetime as _dt
            parsed_date = _dt.strptime(raw, "%Y-%m-%d").date()
        except ValueError:
            pass
    if parsed_date is None and len(raw) >= 8 and "-" in raw:
        # MM-DD-YYYY
        for fmt in ("%m-%d-%Y", "%m-%d-%y"):
            try:
                from datetime import datetime as _dt
                parsed_date = _dt.strptime(raw, fmt).date()
                break
            except ValueError:
                continue

    if parsed_date:
        # Search by birth date
        filters.append(BillingRecord.birth_date == parsed_date)
    elif raw.isdigit():
        # Numeric — search patient_id (chart number) and topaz_id
        filters.append(or_(
            cast(BillingRecord.patient_id, String).ilike(f"%{raw}%"),
            BillingRecord.topaz_id.ilike(f"%{raw}%"),
        ))
    else:
        # Name search — case-insensitive partial match
        search = f"%{raw.upper()}%"
        filters.append(or_(
            BillingRecord.patient_name.ilike(search),
            BillingRecord.patient_name_display.ilike(search),
        ))

    result = await db.execute(
        select(
            BillingRecord.patient_name,
            BillingRecord.patient_id,
            func.count(BillingRecord.id).label("visit_count"),
            func.sum(BillingRecord.total_payment).label("total_paid"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("unpaid_count"),
            func.min(BillingRecord.service_date).label("first_visit"),
            func.max(BillingRecord.service_date).label("last_visit"),
            func.max(BillingRecord.insurance_carrier).label("insurance"),
            func.max(BillingRecord.birth_date).label("birth_date"),
            func.max(BillingRecord.topaz_id).label("topaz_id"),
        )
        .where(*filters)
        .group_by(BillingRecord.patient_name, BillingRecord.patient_id)
        .order_by(BillingRecord.patient_name)
        .limit(limit)
    )
    patients = []
    for r in result.all():
        patients.append({
            "patient_name": r.patient_name,
            "patient_id": r.patient_id,
            "visit_count": r.visit_count,
            "total_paid": float(r.total_paid or 0),
            "unpaid_count": r.unpaid_count,
            "first_visit": r.first_visit.isoformat() if r.first_visit else None,
            "last_visit": r.last_visit.isoformat() if r.last_visit else None,
            "insurance": r.insurance,
            "birth_date": r.birth_date.isoformat() if r.birth_date else None,
            "topaz_id": r.topaz_id,
        })
    return {"patients": patients, "total": len(patients)}


@router.get("/patients/{patient_name:path}/detail")
async def patient_detail(patient_name: str, db: AsyncSession = Depends(get_db)):
    """Full billing history for a patient — every visit with payment status and why."""
    from backend.app.revenue.denial_actions import get_denial_detail
    from backend.app.models.payer import FeeSchedule

    # All billing records for this patient
    result = await db.execute(
        select(BillingRecord)
        .where(BillingRecord.patient_name == patient_name)
        .order_by(BillingRecord.service_date.desc())
    )
    records = result.scalars().all()

    if not records:
        return {"patient_name": patient_name, "visits": [], "summary": {}}

    # Fee schedule for underpayment detection
    fee_result = await db.execute(select(FeeSchedule))
    fee_map = {}
    for f in fee_result.scalars().all():
        key = (f.payer_code, f.modality)
        fee_map[key] = float(f.expected_rate)
        fee_map[("DEFAULT", f.modality)] = fee_map.get(("DEFAULT", f.modality), float(f.expected_rate))

    visits = []
    total_billed = 0
    total_paid = 0
    total_unpaid = 0
    total_underpaid = 0

    for r in records:
        payment = float(r.total_payment or 0)
        primary = float(r.primary_payment or 0)
        secondary = float(r.secondary_payment or 0)
        total_paid += payment

        # Determine payment status and reason
        expected = fee_map.get((r.insurance_carrier, r.modality)) or fee_map.get(("DEFAULT", r.modality)) or 0
        total_billed += expected

        if r.insurance_carrier == "X" or r.denial_status == "WRITTEN_OFF":
            status = "WRITTEN_OFF"
            reason = "Written off"
            action = None
            fix = None
        elif r.denial_status and r.denial_status not in ("RESOLVED", "PAID_ON_APPEAL", "WRITTEN_OFF"):
            status = "DENIED"
            denial_info = get_denial_detail(
                r.denial_reason_code,
                billed_amount=expected,
                paid_amount=payment,
            )
            reason = denial_info.get("carc_description", r.denial_reason_code or "Unknown denial")
            action = denial_info.get("recommended_action", "REVIEW")
            fix = denial_info.get("fix_instructions", "")
        elif payment == 0 and expected > 0:
            status = "UNPAID"
            total_unpaid += 1
            # Figure out why
            if r.appeal_deadline and r.appeal_deadline < date.today():
                reason = "Filing deadline passed"
                action = "WRITE_OFF"
                fix = "Deadline expired — may not be recoverable"
            else:
                reason = "No payment received"
                action = "FOLLOW_UP"
                fix = "Contact payer to check claim status"
        elif expected > 0 and payment < expected * 0.80:
            status = "UNDERPAID"
            total_underpaid += 1
            reason = f"Paid ${payment:,.2f} vs expected ${expected:,.2f} ({payment/expected*100:.0f}%)"
            action = "REVIEW"
            fix = "Compare EOB to fee schedule — may need appeal"
        elif payment > 0:
            status = "PAID"
            reason = None
            action = None
            fix = None
        else:
            status = "NO_CHARGE"
            reason = None
            action = None
            fix = None

        # Check missing secondary
        missing_secondary = False
        if primary > 0 and secondary == 0 and r.insurance_carrier in ("M/M", "CALOPTIMA"):
            missing_secondary = True

        visits.append({
            "id": r.id,
            "service_date": r.service_date.isoformat() if r.service_date else None,
            "modality": r.modality,
            "scan_type": r.scan_type,
            "description": r.description,
            "referring_doctor": r.referring_doctor,
            "insurance_carrier": r.insurance_carrier,
            "primary_payment": primary,
            "secondary_payment": secondary,
            "total_payment": payment,
            "expected_payment": expected,
            "gado_used": r.gado_used,
            "status": status,
            "reason": reason,
            "action": action,
            "fix": fix,
            "denial_status": r.denial_status,
            "denial_reason_code": r.denial_reason_code,
            "appeal_deadline": r.appeal_deadline.isoformat() if r.appeal_deadline else None,
            "missing_secondary": missing_secondary,
        })

    # Summary
    first_record = records[-1]
    summary = {
        "patient_name": patient_name,
        "patient_id": first_record.patient_id,
        "birth_date": first_record.birth_date.isoformat() if first_record.birth_date else None,
        "topaz_id": first_record.topaz_id,
        "total_visits": len(records),
        "total_paid": round(total_paid, 2),
        "total_expected": round(total_billed, 2),
        "total_unpaid": total_unpaid,
        "total_underpaid": total_underpaid,
        "collection_rate": round(total_paid / total_billed * 100, 1) if total_billed > 0 else 0,
        "carriers": list(set(r.insurance_carrier for r in records)),
        "first_visit": records[-1].service_date.isoformat() if records[-1].service_date else None,
        "last_visit": records[0].service_date.isoformat() if records[0].service_date else None,
    }

    # ERA matches for this patient
    era_matches = []
    billing_ids = [r.id for r in records]
    if billing_ids:
        era_result = await db.execute(
            select(ERAClaimLine)
            .where(ERAClaimLine.matched_billing_id.in_(billing_ids))
            .order_by(ERAClaimLine.service_date_835.desc())
        )
        for ecl in era_result.scalars().all():
            era_matches.append({
                "claim_id": ecl.claim_id,
                "payer_name": None,
                "service_date": ecl.service_date_835.isoformat() if ecl.service_date_835 else None,
                "billed_amount": float(ecl.billed_amount) if ecl.billed_amount else None,
                "paid_amount": float(ecl.paid_amount) if ecl.paid_amount else None,
                "confidence": float(ecl.match_confidence) if ecl.match_confidence else None,
                "claim_status": ecl.claim_status,
            })

    return {"summary": summary, "visits": visits, "era_matches": era_matches}


@router.get("/patients/by-record/{billing_record_id}")
async def patient_by_record(billing_record_id: int, db: AsyncSession = Depends(get_db)):
    """Get patient name from a billing record ID — used by PatientDrilldown modal."""
    result = await db.execute(
        select(BillingRecord.patient_name)
        .where(BillingRecord.id == billing_record_id)
    )
    row = result.scalar_one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Billing record not found")
    return {"patient_name": row}
