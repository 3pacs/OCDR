"""Session Log System.

Generates structured reports from insight_logs for AI session continuity.
"""

from datetime import datetime, date, timedelta

from sqlalchemy import func, case, and_

from app.models import db, BillingRecord, EraClaimLine, Payer, InsightLog


def generate_session_report() -> dict:
    """Generate a comprehensive report for future AI sessions."""
    report = {
        "generated_at": str(datetime.utcnow()),
        "report_version": "1.0",
    }
    report["system_state"] = _get_system_state()
    report["open_insights"] = _get_open_insights()
    report["resolved_insights"] = _get_resolved_insights()
    report["key_metrics"] = _get_key_metrics()
    report["priority_actions"] = _synthesize_actions(report)
    report["session_context"] = _build_session_context(report)
    return report


def _get_system_state() -> dict:
    r = db.session.query(
        func.count().label("total"),
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
        func.sum(case((BillingRecord.era_claim_id.isnot(None), 1), else_=0)).label("era_linked"),
        func.min(BillingRecord.service_date).label("earliest"),
        func.max(BillingRecord.service_date).label("latest"),
    ).one()

    era_count = db.session.query(func.count()).select_from(EraClaimLine).scalar() or 0

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


def _get_open_insights() -> list[dict]:
    severity_order = case(
        (InsightLog.severity == "CRITICAL", 0),
        (InsightLog.severity == "HIGH", 1),
        (InsightLog.severity == "MEDIUM", 2),
        (InsightLog.severity == "LOW", 3),
        else_=4,
    )
    logs = InsightLog.query.filter(
        InsightLog.status.in_(["OPEN", "IN_PROGRESS", "ACKNOWLEDGED"])
    ).order_by(severity_order, InsightLog.estimated_impact.desc().nulls_last()).all()

    return [{
        "id": log.id, "category": log.category, "severity": log.severity,
        "title": log.title, "description": log.description,
        "recommendation": log.recommendation,
        "estimated_impact": float(log.estimated_impact) if log.estimated_impact else None,
        "affected_count": log.affected_count,
        "entity_type": log.entity_type, "entity_id": log.entity_id,
        "status": log.status, "created_at": str(log.created_at), "data": log.data,
    } for log in logs]


def _get_resolved_insights() -> list[dict]:
    logs = InsightLog.query.filter(
        InsightLog.status.in_(["RESOLVED", "DISMISSED"])
    ).order_by(InsightLog.resolved_at.desc().nulls_last()).limit(20).all()

    return [{
        "id": log.id, "category": log.category, "title": log.title,
        "status": log.status, "resolution_notes": log.resolution_notes,
        "estimated_impact": float(log.estimated_impact) if log.estimated_impact else None,
        "resolved_at": str(log.resolved_at) if log.resolved_at else None,
    } for log in logs]


def _get_key_metrics() -> dict:
    today = date.today()

    denial_result = db.session.query(
        func.coalesce(BillingRecord.denial_status, "DENIED").label("status"),
        func.count().label("count"),
    ).filter(BillingRecord.total_payment == 0).group_by("status").all()
    denial_by_status = {r.status: r.count for r in denial_result}

    sec_missing = db.session.query(func.count()).filter(
        BillingRecord.primary_payment > 0,
        BillingRecord.secondary_payment == 0,
        BillingRecord.insurance_carrier.in_(["M/M"]),
    ).scalar() or 0

    past_deadline = db.session.query(func.count()).filter(
        BillingRecord.total_payment == 0,
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline < today,
    ).scalar() or 0

    insight_result = db.session.query(
        InsightLog.status.label("status"), func.count().label("count"),
    ).group_by(InsightLog.status).all()
    insights_by_status = {r.status: r.count for r in insight_result}

    return {
        "denial_by_status": denial_by_status,
        "secondary_missing_count": sec_missing,
        "past_filing_deadline": past_deadline,
        "insights_by_status": insights_by_status,
        "measured_at": str(today),
    }


def _synthesize_actions(report: dict) -> list[dict]:
    actions = []
    for insight in report.get("open_insights", [])[:5]:
        actions.append({
            "priority": len(actions) + 1,
            "insight_id": insight["id"],
            "action": insight["recommendation"],
            "category": insight["category"],
            "severity": insight["severity"],
            "estimated_impact": insight.get("estimated_impact"),
            "instruction": f"[{insight['severity']}] {insight['title']}: {insight['recommendation']}",
        })

    past = report.get("key_metrics", {}).get("past_filing_deadline", 0)
    if past > 0 and not any(a["category"] == "FILING_RISK" for a in actions):
        actions.insert(0, {
            "priority": 0, "insight_id": None,
            "action": f"URGENT: {past} claims past filing deadline.",
            "category": "FILING_RISK", "severity": "CRITICAL",
            "estimated_impact": past * 500,
            "instruction": f"[CRITICAL] {past} claims past filing deadline. Open /filing-deadlines.",
        })
    return actions


def _build_session_context(report: dict) -> str:
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

    return "\n".join(lines)


def get_session_briefing() -> str:
    """Quick briefing for a new session."""
    report = generate_session_report()
    return report["session_context"]


def update_insight_status(insight_id: int, status: str, notes: str | None = None) -> dict:
    """Update an insight's status."""
    valid = {"OPEN", "ACKNOWLEDGED", "IN_PROGRESS", "RESOLVED", "DISMISSED"}
    status = status.upper()
    if status not in valid:
        return {"error": f"Status must be one of: {', '.join(sorted(valid))}"}

    log = InsightLog.query.get(insight_id)
    if not log:
        return {"error": "Insight not found", "id": insight_id}

    log.status = status
    if notes:
        log.resolution_notes = notes
    if status in ("RESOLVED", "DISMISSED"):
        log.resolved_at = datetime.utcnow()

    db.session.commit()
    return {"id": insight_id, "status": status}
