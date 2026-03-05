"""Session Log System.

Generates structured reports from insight_logs that can be read back
by future AI conversations to provide specific, data-driven instructions.

The report format is designed to be machine-readable while also being
human-friendly. Each report includes:
- Current system state snapshot
- Open insights requiring action
- Resolved insights with outcomes
- Trend data for tracking improvement over time
- Specific actionable instructions for the next session
"""

from datetime import datetime, date, timedelta

from sqlalchemy import select, func, case, and_
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAClaimLine
from backend.app.models.payer import Payer
from backend.app.models.insight_log import InsightLog


async def generate_session_report(db: AsyncSession) -> dict:
    """Generate a comprehensive report for future AI sessions.

    This report is the primary handoff mechanism between conversations.
    It contains everything a future session needs to pick up where
    the last one left off.
    """
    report = {
        "generated_at": str(datetime.utcnow()),
        "report_version": "1.0",
    }

    # 1. System state snapshot
    report["system_state"] = await _get_system_state(db)

    # 2. Open insights (things that need action)
    report["open_insights"] = await _get_open_insights(db)

    # 3. Recently resolved (track what worked)
    report["resolved_insights"] = await _get_resolved_insights(db)

    # 4. Key metrics for trend tracking
    report["key_metrics"] = await _get_key_metrics(db)

    # 5. Priority action items (synthesized instructions)
    report["priority_actions"] = _synthesize_actions(report)

    # 6. Context for next session
    report["session_context"] = _build_session_context(report)

    return report


async def _get_system_state(db: AsyncSession) -> dict:
    """Current state of the billing system."""
    total_q = select(
        func.count().label("total"),
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
        func.sum(case((BillingRecord.era_claim_id.isnot(None), 1), else_=0)).label("era_linked"),
        func.min(BillingRecord.service_date).label("earliest"),
        func.max(BillingRecord.service_date).label("latest"),
    )
    r = (await db.execute(total_q)).one()

    era_q = select(func.count()).select_from(ERAClaimLine)
    era_count = (await db.execute(era_q)).scalar() or 0

    return {
        "total_billing_records": r.total,
        "total_revenue": float(r.revenue or 0),
        "total_denied": r.denied,
        "denial_rate_pct": round(r.denied / r.total * 100, 1) if r.total else 0,
        "era_linked_records": r.era_linked,
        "era_link_rate_pct": round(r.era_linked / r.total * 100, 1) if r.total else 0,
        "era_claim_lines": era_count,
        "date_range": f"{r.earliest} to {r.latest}" if r.earliest else "No data",
        "snapshot_date": str(date.today()),
    }


async def _get_open_insights(db: AsyncSession) -> list[dict]:
    """Get all open insights, ordered by severity and impact."""
    severity_order = case(
        (InsightLog.severity == "CRITICAL", 0),
        (InsightLog.severity == "HIGH", 1),
        (InsightLog.severity == "MEDIUM", 2),
        (InsightLog.severity == "LOW", 3),
        else_=4,
    )

    q = (
        select(InsightLog)
        .where(InsightLog.status.in_(["OPEN", "IN_PROGRESS", "ACKNOWLEDGED"]))
        .order_by(severity_order, InsightLog.estimated_impact.desc().nulls_last())
    )
    result = await db.execute(q)

    insights = []
    for log in result.scalars():
        insights.append({
            "id": log.id,
            "category": log.category,
            "severity": log.severity,
            "title": log.title,
            "description": log.description,
            "recommendation": log.recommendation,
            "estimated_impact": float(log.estimated_impact) if log.estimated_impact else None,
            "affected_count": log.affected_count,
            "entity_type": log.entity_type,
            "entity_id": log.entity_id,
            "status": log.status,
            "created_at": str(log.created_at),
            "data": log.data,
        })

    return insights


async def _get_resolved_insights(db: AsyncSession) -> list[dict]:
    """Get recently resolved insights to track what worked."""
    q = (
        select(InsightLog)
        .where(InsightLog.status.in_(["RESOLVED", "DISMISSED"]))
        .order_by(InsightLog.resolved_at.desc().nulls_last())
        .limit(20)
    )
    result = await db.execute(q)

    return [
        {
            "id": log.id,
            "category": log.category,
            "title": log.title,
            "status": log.status,
            "resolution_notes": log.resolution_notes,
            "estimated_impact": float(log.estimated_impact) if log.estimated_impact else None,
            "resolved_at": str(log.resolved_at) if log.resolved_at else None,
        }
        for log in result.scalars()
    ]


async def _get_key_metrics(db: AsyncSession) -> dict:
    """Key metrics for trend tracking across sessions."""
    today = date.today()

    # Denial counts by status
    denial_q = (
        select(
            func.coalesce(BillingRecord.denial_status, "DENIED").label("status"),
            func.count().label("count"),
        )
        .where(BillingRecord.total_payment == 0)
        .group_by(func.coalesce(BillingRecord.denial_status, "DENIED"))
    )
    denial_result = await db.execute(denial_q)
    denial_by_status = {r.status: r.count for r in denial_result}

    # Secondary followup
    sec_q = select(func.count()).where(
        BillingRecord.primary_payment > 0,
        BillingRecord.secondary_payment == 0,
        BillingRecord.insurance_carrier.in_(["M/M", "CALOPTIMA"]),
    )
    sec_missing = (await db.execute(sec_q)).scalar() or 0

    # Filing deadlines
    past_q = select(func.count()).where(
        BillingRecord.total_payment == 0,
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline < today,
    )
    past_deadline = (await db.execute(past_q)).scalar() or 0

    # Insight counts
    insight_q = (
        select(
            InsightLog.status.label("status"),
            func.count().label("count"),
        )
        .group_by(InsightLog.status)
    )
    insight_result = await db.execute(insight_q)
    insights_by_status = {r.status: r.count for r in insight_result}

    return {
        "denial_by_status": denial_by_status,
        "secondary_missing_count": sec_missing,
        "past_filing_deadline": past_deadline,
        "insights_by_status": insights_by_status,
        "measured_at": str(today),
    }


def _synthesize_actions(report: dict) -> list[dict]:
    """Synthesize top priority actions from the report data."""
    actions = []

    # From open insights, take top 5 by impact
    for insight in report.get("open_insights", [])[:5]:
        actions.append({
            "priority": len(actions) + 1,
            "insight_id": insight["id"],
            "action": insight["recommendation"],
            "category": insight["category"],
            "severity": insight["severity"],
            "estimated_impact": insight.get("estimated_impact"),
            "instruction": (
                f"[{insight['severity']}] {insight['title']}: {insight['recommendation']}"
            ),
        })

    # Filing deadline urgency
    past = report.get("key_metrics", {}).get("past_filing_deadline", 0)
    if past > 0 and not any(a["category"] == "FILING_RISK" for a in actions):
        actions.insert(0, {
            "priority": 0,
            "insight_id": None,
            "action": f"URGENT: {past} claims past filing deadline. Review immediately in Filing Deadlines page.",
            "category": "FILING_RISK",
            "severity": "CRITICAL",
            "estimated_impact": past * 500,
            "instruction": f"[CRITICAL] {past} claims past filing deadline. Open /filing-deadlines and process all PAST_DEADLINE items.",
        })

    return actions


def _build_session_context(report: dict) -> str:
    """Build a natural language context string for the next AI session.

    This is the key output — a structured briefing that future Claude
    sessions can read to understand what happened and what to do.
    """
    state = report.get("system_state", {})
    metrics = report.get("key_metrics", {})
    open_count = len(report.get("open_insights", []))
    resolved_count = len(report.get("resolved_insights", []))
    actions = report.get("priority_actions", [])

    lines = [
        f"=== OCMRI BILLING SYSTEM SESSION REPORT ({report.get('generated_at', 'unknown')}) ===",
        "",
        f"SYSTEM STATE: {state.get('total_billing_records', 0):,} billing records, "
        f"${state.get('total_revenue', 0):,.0f} total revenue, "
        f"{state.get('denial_rate_pct', 0)}% denial rate, "
        f"{state.get('era_link_rate_pct', 0)}% ERA-linked.",
        "",
        f"INSIGHTS: {open_count} open, {resolved_count} recently resolved.",
        "",
    ]

    if actions:
        lines.append("PRIORITY ACTIONS (do these first):")
        for a in actions[:5]:
            lines.append(f"  {a['priority']}. {a['instruction']}")
        lines.append("")

    # Key numbers for trend tracking
    denial_status = metrics.get("denial_by_status", {})
    if denial_status:
        lines.append(f"DENIAL STATUS: {denial_status}")

    sec = metrics.get("secondary_missing_count", 0)
    if sec:
        lines.append(f"SECONDARY MISSING: {sec} claims need secondary billing follow-up")

    past = metrics.get("past_filing_deadline", 0)
    if past:
        lines.append(f"FILING DEADLINES: {past} claims past deadline")

    lines.append("")
    lines.append("To get detailed data, call GET /api/insights/report")
    lines.append("To see recommendations, call GET /api/insights/recommendations")
    lines.append("To see the knowledge graph, call GET /api/insights/graph")

    return "\n".join(lines)


async def get_session_briefing(db: AsyncSession) -> str:
    """Quick briefing for a new session — returns the context string only."""
    report = await generate_session_report(db)
    return report["session_context"]


async def update_insight_status(
    db: AsyncSession,
    insight_id: int,
    status: str,
    notes: str | None = None,
) -> dict:
    """Update an insight's status."""
    valid = {"OPEN", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "DISMISSED"}
    status = status.upper()
    if status not in valid:
        return {"error": f"Status must be one of: {', '.join(sorted(valid))}"}

    q = select(InsightLog).where(InsightLog.id == insight_id)
    result = await db.execute(q)
    log = result.scalar_one_or_none()
    if not log:
        return {"error": "Insight not found", "id": insight_id}

    log.status = status
    if notes:
        log.resolution_notes = notes
    if status in ("RESOLVED", "DISMISSED"):
        log.resolved_at = datetime.utcnow()

    await db.commit()
    return {"id": insight_id, "status": status}
