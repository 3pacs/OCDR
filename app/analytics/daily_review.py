"""AI daily system review — automated health checks on billing data.

Called by the /api/analytics/daily-review endpoint.
Results are returned as structured data AND appended to TASKS.md.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import func, and_, or_, case

from app.models import db, BillingRecord, EraClaimLine, InsightLog

logger = logging.getLogger(__name__)


def run_daily_review() -> dict:
    """Run all daily review checks. Returns structured findings."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    month_ahead = today + timedelta(days=30)

    findings = {
        "date": today.isoformat(),
        "sections": [],
        "critical_alerts": [],
        "summary": "",
    }

    # ── 1. Data Quality ──
    section = {"title": "Data Quality", "items": []}

    recent = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.service_date >= week_ago
    ).scalar() or 0
    section["items"].append(f"Records with service_date in last 7 days: {recent}")

    total_records = db.session.query(func.count(BillingRecord.id)).scalar() or 0
    section["items"].append(f"Total billing records: {total_records:,}")

    missing_ins_count = db.session.query(func.count(BillingRecord.id)).filter(
        or_(BillingRecord.insurance_carrier.is_(None), BillingRecord.insurance_carrier == "")
    ).scalar() or 0
    if missing_ins_count > 0:
        section["items"].append(f"WARNING: {missing_ins_count} records missing insurance carrier")
        findings["critical_alerts"].append(f"{missing_ins_count} records missing insurance carrier")

    findings["sections"].append(section)

    # ── 2. Match Rate ──
    section = {"title": "ERA Match Rate", "items": []}

    total_era_count = db.session.query(func.count(EraClaimLine.id)).scalar() or 0
    matched_count = db.session.query(func.count(EraClaimLine.id)).filter(
        EraClaimLine.matched_billing_id.is_not(None)
    ).scalar() or 0
    unmatched_count = total_era_count - matched_count

    match_rate = (matched_count / total_era_count * 100) if total_era_count > 0 else 0
    section["items"].append(f"Total ERA claims: {total_era_count:,}")
    section["items"].append(f"Matched: {matched_count:,} ({match_rate:.1f}%)")
    section["items"].append(f"Unmatched: {unmatched_count:,}")

    if match_rate < 95 and total_era_count > 0:
        section["items"].append(f"WARNING: Match rate {match_rate:.1f}% is below 95% target")
        findings["critical_alerts"].append(f"ERA match rate {match_rate:.1f}% below target")

    high_conf_count = db.session.query(func.count(EraClaimLine.id)).filter(
        and_(
            EraClaimLine.matched_billing_id.is_not(None),
            EraClaimLine.match_confidence >= 0.9,
        )
    ).scalar() or 0
    if matched_count > 0:
        section["items"].append(f"High confidence (>=90%): {high_conf_count:,} ({high_conf_count/matched_count*100:.0f}% of matches)")

    findings["sections"].append(section)

    # ── 3. Denial Trends ──
    section = {"title": "Denial Trends", "items": []}

    denied_count = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.denial_status.is_not(None)
    ).scalar() or 0
    denial_rate = (denied_count / total_records * 100) if total_records > 0 else 0
    section["items"].append(f"Total denied claims: {denied_count:,} ({denial_rate:.1f}% of all records)")

    if denial_rate > 5:
        section["items"].append(f"WARNING: Denial rate {denial_rate:.1f}% exceeds 5% industry benchmark")
        findings["critical_alerts"].append(f"Denial rate {denial_rate:.1f}% above benchmark")

    top_denial_rows = db.session.query(
        BillingRecord.denial_reason_code,
        func.count(BillingRecord.id).label("cnt"),
    ).filter(
        BillingRecord.denial_reason_code.is_not(None)
    ).group_by(BillingRecord.denial_reason_code).order_by(
        func.count(BillingRecord.id).desc()
    ).limit(5).all()

    if top_denial_rows:
        section["items"].append("Top denial codes:")
        for code, cnt in top_denial_rows:
            section["items"].append(f"  - {code}: {cnt} claims")

    approaching_count = db.session.query(func.count(BillingRecord.id)).filter(
        and_(
            BillingRecord.denial_status.is_not(None),
            BillingRecord.appeal_deadline.is_not(None),
            BillingRecord.appeal_deadline <= month_ahead,
            BillingRecord.appeal_deadline >= today,
        )
    ).scalar() or 0
    if approaching_count > 0:
        section["items"].append(f"ATTENTION: {approaching_count} claims with appeal deadline in next 30 days")
        if approaching_count > 10:
            findings["critical_alerts"].append(f"{approaching_count} appeal deadlines in next 30 days")

    findings["sections"].append(section)

    # ── 4. Revenue Pulse ──
    section = {"title": "Revenue Pulse", "items": []}

    total_pay = db.session.query(func.sum(BillingRecord.total_payment)).filter(
        BillingRecord.total_payment > 0
    ).scalar() or 0
    section["items"].append(f"Total payments on record: ${float(total_pay):,.2f}")

    zero_pay_count = db.session.query(func.count(BillingRecord.id)).filter(
        and_(
            BillingRecord.total_payment == 0,
            BillingRecord.denial_status.is_(None),
            BillingRecord.service_date >= week_ago,
        )
    ).scalar() or 0
    if zero_pay_count > 0:
        section["items"].append(f"Records with $0 payment (no denial, last 7 days): {zero_pay_count}")

    topaz_count = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.topaz_patient_id.is_not(None)
    ).scalar() or 0
    topaz_pct = (topaz_count / total_records * 100) if total_records > 0 else 0
    section["items"].append(f"Topaz ID coverage: {topaz_count:,}/{total_records:,} ({topaz_pct:.1f}%)")

    if topaz_pct < 80 and total_records > 100:
        section["items"].append(f"WARNING: Topaz ID coverage {topaz_pct:.1f}% is low — affects matching")
        findings["critical_alerts"].append(f"Topaz ID coverage only {topaz_pct:.1f}%")

    findings["sections"].append(section)

    # ── 5. Pipeline Suggestions Status ──
    section = {"title": "Pipeline Suggestions", "items": []}

    pipeline_counts = db.session.query(
        InsightLog.status, func.count(InsightLog.id)
    ).filter(
        InsightLog.category.like("PIPELINE_%")
    ).group_by(InsightLog.status).all()

    status_counts = {row[0]: row[1] for row in pipeline_counts}
    total_suggestions = sum(status_counts.values())

    if total_suggestions > 0:
        section["items"].append(f"Total pipeline suggestions: {total_suggestions}")
        for status, count in sorted(status_counts.items()):
            section["items"].append(f"  - {status}: {count}")
        open_count = status_counts.get("OPEN", 0)
        if open_count > 5:
            section["items"].append(f"NOTE: {open_count} suggestions still OPEN — review at /pipeline")
    else:
        section["items"].append("No pipeline suggestions yet — visit /pipeline to generate them")

    findings["sections"].append(section)

    # ── 6. System Health ──
    section = {"title": "System Health", "items": []}
    section["items"].append(f"Total billing records: {total_records:,}")
    section["items"].append(f"Total ERA claims: {total_era_count:,}")
    section["items"].append(f"Matched claims: {matched_count:,}")

    mod_rows = db.session.query(
        BillingRecord.modality, func.count(BillingRecord.id)
    ).filter(
        BillingRecord.modality.is_not(None)
    ).group_by(BillingRecord.modality).order_by(
        func.count(BillingRecord.id).desc()
    ).limit(8).all()

    if mod_rows:
        section["items"].append("Top modalities:")
        for mod, cnt in mod_rows:
            section["items"].append(f"  - {mod}: {cnt:,}")

    findings["sections"].append(section)

    # ── Build summary ──
    alert_count = len(findings["critical_alerts"])
    if alert_count == 0:
        findings["summary"] = f"All clear. {total_records:,} records, {match_rate:.1f}% match rate, {denial_rate:.1f}% denial rate."
    else:
        findings["summary"] = f"{alert_count} alert(s) need attention. {total_records:,} records, {match_rate:.1f}% match rate, {denial_rate:.1f}% denial rate."

    return findings


def format_review_markdown(findings: dict) -> str:
    """Convert review findings to markdown for TASKS.md."""
    lines = []
    lines.append(f"## Daily Review — {findings['date']}")
    lines.append("")
    lines.append(f"**{findings['summary']}**")
    lines.append("")

    if findings["critical_alerts"]:
        lines.append("### Alerts")
        for alert in findings["critical_alerts"]:
            lines.append(f"- {alert}")
        lines.append("")

    for section in findings["sections"]:
        lines.append(f"### {section['title']}")
        for item in section["items"]:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)
