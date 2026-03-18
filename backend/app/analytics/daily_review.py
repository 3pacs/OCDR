"""AI daily system review — automated health checks on billing data.

Called by the /api/analytics/daily-review endpoint.
Results are returned as structured data AND appended to TASKS.md.
"""

import logging
from datetime import date, timedelta

from sqlalchemy import select, func, and_, or_, case, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAClaimLine
from backend.app.models.insight_log import InsightLog

logger = logging.getLogger(__name__)


async def run_daily_review(db: AsyncSession) -> dict:
    """Run all daily review checks. Returns structured findings."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    week_ago = today - timedelta(days=7)
    month_ahead = today + timedelta(days=30)

    findings = {
        "date": today.isoformat(),
        "sections": [],
        "critical_alerts": [],
        "summary": "",
    }

    # ── 1. Data Quality ──────────────────────────────────────────────────
    section = {"title": "Data Quality", "items": []}

    # Records imported recently
    recent_count = await db.execute(
        select(func.count(BillingRecord.id)).where(
            BillingRecord.service_date >= week_ago
        )
    )
    recent = recent_count.scalar() or 0
    section["items"].append(f"Records with service_date in last 7 days: {recent}")

    # Total records
    total_result = await db.execute(select(func.count(BillingRecord.id)))
    total_records = total_result.scalar() or 0
    section["items"].append(f"Total billing records: {total_records:,}")

    # Missing key fields
    missing_insurance = await db.execute(
        select(func.count(BillingRecord.id)).where(
            or_(
                BillingRecord.insurance_carrier.is_(None),
                BillingRecord.insurance_carrier == "",
            )
        )
    )
    missing_ins_count = missing_insurance.scalar() or 0
    if missing_ins_count > 0:
        section["items"].append(f"WARNING: {missing_ins_count} records missing insurance carrier")
        findings["critical_alerts"].append(f"{missing_ins_count} records missing insurance carrier")

    findings["sections"].append(section)

    # ── 2. Match Rate ────────────────────────────────────────────────────
    section = {"title": "ERA Match Rate", "items": []}

    total_era = await db.execute(select(func.count(ERAClaimLine.id)))
    total_era_count = total_era.scalar() or 0

    matched_era = await db.execute(
        select(func.count(ERAClaimLine.id)).where(
            ERAClaimLine.matched_billing_id.is_not(None)
        )
    )
    matched_count = matched_era.scalar() or 0
    unmatched_count = total_era_count - matched_count

    match_rate = (matched_count / total_era_count * 100) if total_era_count > 0 else 0
    section["items"].append(f"Total ERA claims: {total_era_count:,}")
    section["items"].append(f"Matched: {matched_count:,} ({match_rate:.1f}%)")
    section["items"].append(f"Unmatched: {unmatched_count:,}")

    if match_rate < 95 and total_era_count > 0:
        section["items"].append(f"WARNING: Match rate {match_rate:.1f}% is below 95% target")
        findings["critical_alerts"].append(f"ERA match rate {match_rate:.1f}% below target")

    # High-confidence matches
    high_conf = await db.execute(
        select(func.count(ERAClaimLine.id)).where(
            and_(
                ERAClaimLine.matched_billing_id.is_not(None),
                ERAClaimLine.match_confidence >= 0.9,
            )
        )
    )
    high_conf_count = high_conf.scalar() or 0
    if matched_count > 0:
        section["items"].append(f"High confidence (≥90%): {high_conf_count:,} ({high_conf_count/matched_count*100:.0f}% of matches)")

    findings["sections"].append(section)

    # ── 3. Denial Trends ─────────────────────────────────────────────────
    section = {"title": "Denial Trends", "items": []}

    denied = await db.execute(
        select(func.count(BillingRecord.id)).where(
            BillingRecord.denial_status.is_not(None)
        )
    )
    denied_count = denied.scalar() or 0
    denial_rate = (denied_count / total_records * 100) if total_records > 0 else 0
    section["items"].append(f"Total denied claims: {denied_count:,} ({denial_rate:.1f}% of all records)")

    if denial_rate > 5:
        section["items"].append(f"WARNING: Denial rate {denial_rate:.1f}% exceeds 5% industry benchmark")
        findings["critical_alerts"].append(f"Denial rate {denial_rate:.1f}% above benchmark")

    # Top denial reasons
    top_denials = await db.execute(
        select(
            BillingRecord.denial_reason_code,
            func.count(BillingRecord.id).label("cnt"),
        )
        .where(BillingRecord.denial_reason_code.is_not(None))
        .group_by(BillingRecord.denial_reason_code)
        .order_by(func.count(BillingRecord.id).desc())
        .limit(5)
    )
    top_denial_rows = top_denials.all()
    if top_denial_rows:
        section["items"].append("Top denial codes:")
        for code, cnt in top_denial_rows:
            section["items"].append(f"  - {code}: {cnt} claims")

    # Approaching appeal deadlines
    approaching_deadline = await db.execute(
        select(func.count(BillingRecord.id)).where(
            and_(
                BillingRecord.denial_status.is_not(None),
                BillingRecord.appeal_deadline.is_not(None),
                BillingRecord.appeal_deadline <= month_ahead,
                BillingRecord.appeal_deadline >= today,
            )
        )
    )
    approaching_count = approaching_deadline.scalar() or 0
    if approaching_count > 0:
        section["items"].append(f"ATTENTION: {approaching_count} claims with appeal deadline in next 30 days")
        if approaching_count > 10:
            findings["critical_alerts"].append(f"{approaching_count} appeal deadlines in next 30 days")

    findings["sections"].append(section)

    # ── 4. Revenue Pulse ─────────────────────────────────────────────────
    section = {"title": "Revenue Pulse", "items": []}

    # Total payments
    total_payments = await db.execute(
        select(func.sum(BillingRecord.total_payment)).where(
            BillingRecord.total_payment > 0
        )
    )
    total_pay = total_payments.scalar() or 0
    section["items"].append(f"Total payments on record: ${float(total_pay):,.2f}")

    # Underpayments (records with total_payment < expected based on fee schedule)
    zero_pay = await db.execute(
        select(func.count(BillingRecord.id)).where(
            and_(
                BillingRecord.total_payment == 0,
                BillingRecord.denial_status.is_(None),
                BillingRecord.service_date >= week_ago,
            )
        )
    )
    zero_pay_count = zero_pay.scalar() or 0
    if zero_pay_count > 0:
        section["items"].append(f"Records with $0 payment (no denial, last 7 days): {zero_pay_count}")

    # Crosswalk coverage
    has_topaz = await db.execute(
        select(func.count(BillingRecord.id)).where(
            BillingRecord.topaz_id.is_not(None)
        )
    )
    topaz_count = has_topaz.scalar() or 0
    topaz_pct = (topaz_count / total_records * 100) if total_records > 0 else 0
    section["items"].append(f"Topaz ID coverage: {topaz_count:,}/{total_records:,} ({topaz_pct:.1f}%)")

    if topaz_pct < 80 and total_records > 100:
        section["items"].append(f"WARNING: Topaz ID coverage {topaz_pct:.1f}% is low — affects matching")
        findings["critical_alerts"].append(f"Topaz ID coverage only {topaz_pct:.1f}%")

    findings["sections"].append(section)

    # ── 5. Pipeline Suggestions Status ───────────────────────────────────
    section = {"title": "Pipeline Suggestions", "items": []}

    pipeline_counts = await db.execute(
        select(InsightLog.status, func.count(InsightLog.id))
        .where(InsightLog.category.like("PIPELINE_%"))
        .group_by(InsightLog.status)
    )
    status_counts = {row[0]: row[1] for row in pipeline_counts.all()}
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

    # ── 6. System Health ─────────────────────────────────────────────────
    section = {"title": "System Health", "items": []}
    section["items"].append(f"Total billing records: {total_records:,}")
    section["items"].append(f"Total ERA claims: {total_era_count:,}")
    section["items"].append(f"Matched claims: {matched_count:,}")

    # Modality distribution
    modality_counts = await db.execute(
        select(BillingRecord.modality, func.count(BillingRecord.id))
        .where(BillingRecord.modality.is_not(None))
        .group_by(BillingRecord.modality)
        .order_by(func.count(BillingRecord.id).desc())
        .limit(8)
    )
    mod_rows = modality_counts.all()
    if mod_rows:
        section["items"].append("Top modalities:")
        for mod, cnt in mod_rows:
            section["items"].append(f"  - {mod}: {cnt:,}")

    findings["sections"].append(section)

    # ── Build summary ────────────────────────────────────────────────────
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
            lines.append(f"- ⚠️ {alert}")
        lines.append("")

    for section in findings["sections"]:
        lines.append(f"### {section['title']}")
        for item in section["items"]:
            lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines)
