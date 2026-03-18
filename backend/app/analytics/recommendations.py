"""Recommendations Engine.

Analyzes the knowledge graph and billing data to generate actionable
insights and practice improvement suggestions. Each recommendation
includes estimated financial impact.

Recommendation categories:
- DENIAL_PATTERN: Recurring denial patterns that need process changes
- UNDERPAYMENT: Systematic underpayment by specific payers
- SECONDARY_MISSING: Missing secondary insurance revenue
- PAYER_TREND: Payer volume/revenue trend alerts
- PHYSICIAN_ALERT: Physician-specific issues
- FILING_RISK: Filing deadline risks
- REVENUE_OPPORTUNITY: Revenue recovery opportunities
- PROCESS_IMPROVEMENT: Workflow and process improvements
"""

from collections import defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import String, or_, select, func, case, extract
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAClaimLine
from backend.app.models.payer import Payer, FeeSchedule
from backend.app.models.insight_log import InsightLog
from backend.app.revenue.writeoff_filter import not_written_off


async def generate_all_recommendations(db: AsyncSession) -> list[dict]:
    """Run all recommendation analyzers and return sorted results."""
    recommendations = []

    analyzers = [
        _analyze_denial_patterns,
        _analyze_payer_underpayment_patterns,
        _analyze_secondary_gaps,
        _analyze_payer_trends,
        _analyze_physician_denial_rates,
        _analyze_filing_risks,
        _analyze_modality_pricing_gaps,
        _analyze_process_improvements,
    ]

    for analyzer in analyzers:
        try:
            results = await analyzer(db)
            recommendations.extend(results)
        except Exception as e:
            recommendations.append({
                "category": "SYSTEM",
                "severity": "LOW",
                "title": f"Analyzer error: {analyzer.__name__}",
                "description": str(e),
                "recommendation": "Check system logs",
                "estimated_impact": 0,
                "affected_count": 0,
            })

    # Sort by impact DESC
    recommendations.sort(key=lambda r: r.get("estimated_impact", 0) or 0, reverse=True)
    return recommendations


async def _analyze_denial_patterns(db: AsyncSession) -> list[dict]:
    """Find recurring denial patterns by payer + modality + reason code."""
    results = []

    # Denial rate by payer+modality (exclude written-off)
    q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            BillingRecord.modality.label("modality"),
            func.count().label("total"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
            func.sum(case((BillingRecord.total_payment > 0, BillingRecord.total_payment), else_=0)).label("avg_paid_rev"),
        )
        .where(not_written_off())
        .group_by(BillingRecord.insurance_carrier, BillingRecord.modality)
        .having(func.count() >= 10)
    )
    rows = await db.execute(q)

    for r in rows:
        denial_rate = r.denied / r.total if r.total else 0
        if denial_rate > 0.15 and r.denied >= 5:
            avg_claim = float(r.avg_paid_rev or 0) / max(r.total - r.denied, 1)
            impact = round(r.denied * avg_claim, 2)

            severity = "CRITICAL" if denial_rate > 0.4 else "HIGH" if denial_rate > 0.25 else "MEDIUM"
            results.append({
                "category": "DENIAL_PATTERN",
                "severity": severity,
                "title": f"{r.carrier} denies {round(denial_rate*100)}% of {r.modality} claims",
                "description": (
                    f"{r.denied} of {r.total} {r.modality} claims from {r.carrier} are denied ($0 payment). "
                    f"Average paid claim for this combo is ${avg_claim:,.0f}."
                ),
                "recommendation": (
                    f"Investigate {r.carrier} {r.modality} denial reasons. Consider: "
                    f"(1) Pre-authorization requirements, "
                    f"(2) Coding review for {r.modality} claims to {r.carrier}, "
                    f"(3) Contact {r.carrier} rep to clarify coverage policy. "
                    f"Fixing half these denials could recover ~${impact/2:,.0f}."
                ),
                "estimated_impact": impact,
                "affected_count": r.denied,
                "entity_type": "PAYER",
                "entity_id": r.carrier,
                "data": {
                    "carrier": r.carrier,
                    "modality": r.modality,
                    "denial_rate": round(denial_rate * 100, 1),
                    "denied_count": r.denied,
                    "total_count": r.total,
                },
            })

    return results


async def _analyze_payer_underpayment_patterns(db: AsyncSession) -> list[dict]:
    """Find payers that systematically underpay vs fee schedule."""
    results = []

    # Get fee schedules
    fs_q = select(FeeSchedule)
    fs_result = await db.execute(fs_q)
    fee_map = {}
    for fs in fs_result.scalars():
        fee_map[(fs.payer_code, fs.modality)] = float(fs.expected_rate)

    # Avg payment by payer+modality where paid > 0 (exclude written-off)
    q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            BillingRecord.modality.label("modality"),
            func.count().label("count"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
            func.sum(BillingRecord.total_payment).label("total_paid"),
        )
        .where(BillingRecord.total_payment > 0, not_written_off())
        .group_by(BillingRecord.insurance_carrier, BillingRecord.modality)
        .having(func.count() >= 10)
    )
    rows = await db.execute(q)

    for r in rows:
        expected = fee_map.get((r.carrier, r.modality)) or fee_map.get(("DEFAULT", r.modality))
        if not expected:
            continue

        avg_pay = float(r.avg_payment or 0)
        pay_rate = avg_pay / expected if expected else 1.0

        if pay_rate < 0.70:
            gap_per_claim = expected - avg_pay
            total_gap = gap_per_claim * r.count

            results.append({
                "category": "UNDERPAYMENT",
                "severity": "HIGH" if pay_rate < 0.50 else "MEDIUM",
                "title": f"{r.carrier} pays {round(pay_rate*100)}% of expected for {r.modality}",
                "description": (
                    f"{r.carrier} averages ${avg_pay:,.0f} per {r.modality} claim vs "
                    f"expected ${expected:,.0f} ({r.count} claims). "
                    f"Total gap: ${total_gap:,.0f}."
                ),
                "recommendation": (
                    f"Review {r.carrier} contract terms for {r.modality}. "
                    f"If contracted rate is higher, file underpayment appeals for the ${total_gap:,.0f} gap. "
                    f"If this is the contracted rate, flag for next contract negotiation cycle."
                ),
                "estimated_impact": round(total_gap, 2),
                "affected_count": r.count,
                "entity_type": "PAYER",
                "entity_id": r.carrier,
                "data": {
                    "carrier": r.carrier,
                    "modality": r.modality,
                    "avg_payment": round(avg_pay, 2),
                    "expected_rate": expected,
                    "pay_rate_pct": round(pay_rate * 100, 1),
                },
            })

    return results


async def _analyze_secondary_gaps(db: AsyncSession) -> list[dict]:
    """Quantify missing secondary insurance revenue."""
    results = []

    # Get payers with expected secondary
    payer_q = select(Payer).where(Payer.expected_has_secondary == True)
    payer_result = await db.execute(payer_q)
    secondary_carriers = {p.code for p in payer_result.scalars()}
    secondary_carriers.update({"M/M", "CALOPTIMA"})

    q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            func.count().label("count"),
            func.sum(BillingRecord.primary_payment).label("total_primary"),
        )
        .where(
            BillingRecord.insurance_carrier.in_(secondary_carriers),
            BillingRecord.primary_payment > 0,
            BillingRecord.secondary_payment == 0,
            not_written_off(),
        )
        .group_by(BillingRecord.insurance_carrier)
        .having(func.count() >= 10)
    )
    rows = await db.execute(q)
    for row in rows:
        carrier = row.carrier
        if row.count and row.count >= 10:
            est_secondary = float(row.total_primary or 0) * 0.335
            results.append({
                "category": "SECONDARY_MISSING",
                "severity": "HIGH" if est_secondary > 100000 else "MEDIUM",
                "title": f"{carrier}: {row.count} claims missing secondary payment",
                "description": (
                    f"{row.count} claims with {carrier} primary payment (${float(row.total_primary or 0):,.0f}) "
                    f"have $0 secondary. Expected secondary ~33.5% = ${est_secondary:,.0f}."
                ),
                "recommendation": (
                    f"Batch-file secondary claims for all {row.count} {carrier} records. "
                    f"Priority: claims within filing deadline. "
                    f"Use the Secondary Follow-Up queue (F-07) to track progress. "
                    f"Consider automated secondary billing workflow."
                ),
                "estimated_impact": round(est_secondary, 2),
                "affected_count": row.count,
                "entity_type": "PAYER",
                "entity_id": carrier,
                "data": {"carrier": carrier, "missing_count": row.count},
            })

    return results


async def _analyze_payer_trends(db: AsyncSession) -> list[dict]:
    """Detect payer volume/revenue trends (declining payers)."""
    results = []

    q = (
        select(
            BillingRecord.insurance_carrier.label("carrier"),
            func.coalesce(
                BillingRecord.service_year,
                extract("year", BillingRecord.service_date).cast(String),
            ).label("year"),
            func.count().label("count"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(BillingRecord.service_date.isnot(None), not_written_off())
        .group_by(BillingRecord.insurance_carrier, BillingRecord.service_year)
    )

    try:
        rows = await db.execute(q)
        carrier_years = defaultdict(dict)
        for r in rows:
            year = str(r.year) if r.year else None
            if year:
                carrier_years[r.carrier][year] = {
                    "count": r.count,
                    "revenue": float(r.revenue or 0),
                }
    except Exception:
        return results

    for carrier, years in carrier_years.items():
        sorted_years = sorted(years.keys())
        if len(sorted_years) < 2:
            continue

        latest = sorted_years[-1]
        prev = sorted_years[-2]

        latest_rev = years[latest]["revenue"]
        prev_rev = years[prev]["revenue"]
        latest_count = years[latest]["count"]
        prev_count = years[prev]["count"]

        if prev_rev > 0:
            rev_change = (latest_rev - prev_rev) / prev_rev
        else:
            continue

        if rev_change < -0.30 and prev_rev > 10000:
            drop_amount = prev_rev - latest_rev
            results.append({
                "category": "PAYER_TREND",
                "severity": "CRITICAL" if rev_change < -0.60 else "HIGH",
                "title": f"{carrier} revenue dropped {abs(round(rev_change*100))}% ({prev} to {latest})",
                "description": (
                    f"{carrier}: ${prev_rev:,.0f} ({prev_count} claims in {prev}) -> "
                    f"${latest_rev:,.0f} ({latest_count} claims in {latest}). "
                    f"Revenue decline: ${drop_amount:,.0f}."
                ),
                "recommendation": (
                    f"Investigate why {carrier} volume dropped. Possible causes: "
                    f"(1) Contract termination — verify contract status, "
                    f"(2) Referral pattern change — check if physicians shifted, "
                    f"(3) Claims routing to different payer code. "
                    f"If contract was terminated, {'write off pending claims' if latest_rev == 0 else 'escalate immediately'}."
                ),
                "estimated_impact": round(drop_amount, 2),
                "affected_count": prev_count - latest_count if prev_count > latest_count else 0,
                "entity_type": "PAYER",
                "entity_id": carrier,
                "data": {
                    "carrier": carrier,
                    "prev_year": prev,
                    "latest_year": latest,
                    "rev_change_pct": round(rev_change * 100, 1),
                },
            })

    return results


async def _analyze_physician_denial_rates(db: AsyncSession) -> list[dict]:
    """Find physicians with abnormally high denial rates."""
    results = []

    q = (
        select(
            BillingRecord.referring_doctor.label("doctor"),
            func.count().label("total"),
            func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
            func.sum(BillingRecord.total_payment).label("revenue"),
        )
        .where(not_written_off())
        .group_by(BillingRecord.referring_doctor)
        .having(func.count() >= 20)
    )
    rows = await db.execute(q)

    # Calculate global denial rate for comparison
    global_q = select(
        func.count().label("total"),
        func.sum(case((BillingRecord.total_payment == 0, 1), else_=0)).label("denied"),
    ).where(not_written_off())
    global_r = (await db.execute(global_q)).one()
    global_rate = global_r.denied / global_r.total if global_r.total else 0

    for r in rows:
        denial_rate = r.denied / r.total if r.total else 0
        if denial_rate > global_rate * 1.5 and r.denied >= 10:
            avg_rev = float(r.revenue or 0) / max(r.total - r.denied, 1)
            impact = round(r.denied * avg_rev, 2)

            results.append({
                "category": "PHYSICIAN_ALERT",
                "severity": "HIGH" if denial_rate > 0.3 else "MEDIUM",
                "title": f"Dr. {r.doctor}: {round(denial_rate*100)}% denial rate (avg: {round(global_rate*100)}%)",
                "description": (
                    f"{r.denied} of {r.total} claims from Dr. {r.doctor} are denied. "
                    f"This is {round(denial_rate/global_rate, 1)}x the practice average of {round(global_rate*100)}%."
                ),
                "recommendation": (
                    f"Review coding and documentation patterns for Dr. {r.doctor}'s referrals. "
                    f"Check if specific payers or modalities drive the denials. "
                    f"Consider a coding training session or pre-authorization checklist for this physician."
                ),
                "estimated_impact": impact,
                "affected_count": r.denied,
                "entity_type": "PHYSICIAN",
                "entity_id": r.doctor,
                "data": {
                    "doctor": r.doctor,
                    "denial_rate": round(denial_rate * 100, 1),
                    "global_rate": round(global_rate * 100, 1),
                },
            })

    return results


async def _analyze_filing_risks(db: AsyncSession) -> list[dict]:
    """Identify claims at risk of missing filing deadlines."""
    results = []

    today = date.today()

    # Claims past deadline (exclude written-off)
    past_q = select(func.count()).where(
        BillingRecord.total_payment == 0,
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline < today,
        not_written_off(),
    )
    past_count = (await db.execute(past_q)).scalar() or 0

    # Claims in warning zone (within 30 days)
    warning_q = select(func.count()).where(
        BillingRecord.total_payment == 0,
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline >= today,
        BillingRecord.appeal_deadline <= today + timedelta(days=30),
        not_written_off(),
    )
    warning_count = (await db.execute(warning_q)).scalar() or 0

    if past_count > 0:
        results.append({
            "category": "FILING_RISK",
            "severity": "CRITICAL",
            "title": f"{past_count} claims past filing deadline — revenue likely lost",
            "description": (
                f"{past_count} unpaid claims have passed their filing deadline. "
                f"These are likely unrecoverable without extraordinary appeal."
            ),
            "recommendation": (
                f"Review the {past_count} past-deadline claims immediately. "
                f"For any within 30 days past deadline, attempt a late appeal citing good cause. "
                f"For older claims, evaluate write-off vs. appeal cost. "
                f"CRITICAL: Implement automated deadline alerting to prevent future losses."
            ),
            "estimated_impact": past_count * 500,  # Conservative estimate
            "affected_count": past_count,
            "entity_type": None,
            "entity_id": None,
            "data": {"past_count": past_count, "warning_count": warning_count},
        })

    if warning_count > 0:
        results.append({
            "category": "FILING_RISK",
            "severity": "HIGH",
            "title": f"{warning_count} claims approaching filing deadline (within 30 days)",
            "description": (
                f"{warning_count} unpaid claims will pass their filing deadline within 30 days."
            ),
            "recommendation": (
                f"Prioritize these {warning_count} claims for immediate action. "
                f"File appeals or follow-up with payers this week. "
                f"Assign to team members with daily status check."
            ),
            "estimated_impact": warning_count * 500,
            "affected_count": warning_count,
            "entity_type": None,
            "entity_id": None,
            "data": {"warning_count": warning_count},
        })

    return results


async def _analyze_modality_pricing_gaps(db: AsyncSession) -> list[dict]:
    """Find modalities where actual reimbursement deviates significantly from fee schedule."""
    results = []

    # Get fee schedules
    fs_q = select(FeeSchedule).where(FeeSchedule.payer_code == "DEFAULT")
    fs_result = await db.execute(fs_q)
    fee_map = {fs.modality: float(fs.expected_rate) for fs in fs_result.scalars()}

    q = (
        select(
            BillingRecord.modality.label("modality"),
            func.count().label("count"),
            func.avg(BillingRecord.total_payment).label("avg_payment"),
            func.sum(BillingRecord.total_payment).label("total_revenue"),
        )
        .where(BillingRecord.total_payment > 0, not_written_off())
        .group_by(BillingRecord.modality)
        .having(func.count() >= 20)
    )
    rows = await db.execute(q)

    for r in rows:
        expected = fee_map.get(r.modality)
        if not expected:
            continue
        avg_pay = float(r.avg_payment or 0)
        ratio = avg_pay / expected

        if ratio < 0.60:
            gap = (expected - avg_pay) * r.count
            results.append({
                "category": "REVENUE_OPPORTUNITY",
                "severity": "HIGH",
                "title": f"{r.modality} reimbursement at {round(ratio*100)}% of fee schedule",
                "description": (
                    f"Average {r.modality} payment is ${avg_pay:,.0f} vs expected ${expected:,.0f}. "
                    f"Across {r.count} claims, the gap is ${gap:,.0f}."
                ),
                "recommendation": (
                    f"Audit {r.modality} fee schedule. If it's accurate, focus on: "
                    f"(1) Contract renegotiation with major payers, "
                    f"(2) Correct CPT coding for {r.modality} procedures, "
                    f"(3) Ensure modifiers are applied correctly."
                ),
                "estimated_impact": round(gap, 2),
                "affected_count": r.count,
                "entity_type": "MODALITY",
                "entity_id": r.modality,
                "data": {
                    "modality": r.modality,
                    "avg_payment": round(avg_pay, 2),
                    "expected_rate": expected,
                    "ratio": round(ratio, 3),
                },
            })

    return results


async def _analyze_process_improvements(db: AsyncSession) -> list[dict]:
    """Suggest workflow improvements based on data patterns."""
    results = []

    # 1. Check for claims with no insurance carrier (X = written off, not missing)
    no_carrier_q = select(func.count()).where(
        or_(
            BillingRecord.insurance_carrier.is_(None),
            BillingRecord.insurance_carrier == "",
        )
    )
    no_carrier = (await db.execute(no_carrier_q)).scalar() or 0
    if no_carrier > 50:
        results.append({
            "category": "PROCESS_IMPROVEMENT",
            "severity": "MEDIUM",
            "title": f"{no_carrier} claims with missing insurance carrier",
            "description": (
                f"{no_carrier} claims have no insurance carrier. "
                f"These cannot be properly billed or followed up."
            ),
            "recommendation": (
                f"Implement front-desk insurance verification checklist. "
                f"Review the {no_carrier} blank carrier claims to identify the actual payer. "
                f"Add insurance verification step to patient intake workflow."
            ),
            "estimated_impact": no_carrier * 200,
            "affected_count": no_carrier,
            "entity_type": None,
            "entity_id": None,
            "data": {"unknown_carrier_count": no_carrier},
        })

    # 2. Check for claims without linked ERA data (exclude written-off)
    no_era_q = select(func.count()).where(
        BillingRecord.era_claim_id.is_(None),
        BillingRecord.total_payment > 0,
        not_written_off(),
    )
    no_era = (await db.execute(no_era_q)).scalar() or 0
    total_paid_q = select(func.count()).where(BillingRecord.total_payment > 0, not_written_off())
    total_paid = (await db.execute(total_paid_q)).scalar() or 0

    if total_paid > 0 and no_era / total_paid > 0.3:
        results.append({
            "category": "PROCESS_IMPROVEMENT",
            "severity": "MEDIUM",
            "title": f"{round(no_era/total_paid*100)}% of paid claims not linked to ERA data",
            "description": (
                f"{no_era} of {total_paid} paid claims have no ERA (835) payment linked. "
                f"This means payment details, denial codes, and adjustment reasons are unavailable."
            ),
            "recommendation": (
                f"Import more 835 files and run the auto-matcher. "
                f"Check with clearinghouse for missing ERA files. "
                f"Consider enrolling in electronic ERA with all payers."
            ),
            "estimated_impact": 0,
            "affected_count": no_era,
            "entity_type": None,
            "entity_id": None,
            "data": {"unlinked_count": no_era, "total_paid": total_paid},
        })

    # 3. GADO tracking improvement
    gado_q = select(
        func.count().label("total"),
        func.sum(case((BillingRecord.gado_used == True, 1), else_=0)).label("with_gado"),
    ).where(BillingRecord.modality.in_(["HMRI", "OPEN"]), not_written_off())
    gado_r = (await db.execute(gado_q)).one()
    if gado_r.total and gado_r.with_gado:
        gado_pct = gado_r.with_gado / gado_r.total
        if gado_pct > 0.3:
            ungado_revenue = (gado_r.total - gado_r.with_gado) * 200  # $200 premium
            results.append({
                "category": "PROCESS_IMPROVEMENT",
                "severity": "LOW",
                "title": f"Verify gado billing: {gado_r.total - gado_r.with_gado} MRI scans without gado flag",
                "description": (
                    f"{gado_r.with_gado} of {gado_r.total} MRI scans are flagged with gado contrast. "
                    f"Verify the remaining {gado_r.total - gado_r.with_gado} didn't use contrast — "
                    f"each missed gado flag is ~$200 in lost premium billing."
                ),
                "recommendation": (
                    f"Cross-reference radiology reports for the {gado_r.total - gado_r.with_gado} "
                    f"MRI scans without gado flag. Implement automatic gado detection from scan reports."
                ),
                "estimated_impact": ungado_revenue * 0.1,  # Assume 10% are actually missing
                "affected_count": gado_r.total - gado_r.with_gado,
                "entity_type": "MODALITY",
                "entity_id": "HMRI",
                "data": {"with_gado": gado_r.with_gado, "total_mri": gado_r.total},
            })

    return results


async def persist_recommendations(db: AsyncSession, recommendations: list[dict]) -> int:
    """Save recommendations to the insight_log table for future reference.

    Only inserts new insights (deduplicates by title).
    """
    # Get existing titles to avoid duplicates
    existing_q = select(InsightLog.title).where(InsightLog.status.in_(["OPEN", "IN_PROGRESS"]))
    existing = {r[0] for r in (await db.execute(existing_q)).fetchall()}

    count = 0
    for rec in recommendations:
        if rec["title"] in existing:
            continue

        log = InsightLog(
            category=rec["category"],
            severity=rec["severity"],
            title=rec["title"],
            description=rec["description"],
            recommendation=rec["recommendation"],
            estimated_impact=rec.get("estimated_impact"),
            affected_count=rec.get("affected_count"),
            entity_type=rec.get("entity_type"),
            entity_id=rec.get("entity_id"),
            data=rec.get("data"),
            status="OPEN",
        )
        db.add(log)
        count += 1

    if count:
        await db.commit()

    return count
