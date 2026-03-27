"""Pipeline Improvement Suggestions Engine.

Analyzes billing data against healthcare industry best practices and
generates actionable improvement suggestions. Auto-refreshed daily.

Categories:
- REVENUE_LEAK: Money left on the table (denials, underpayments, missed secondary)
- COMPLIANCE: HIPAA, timely filing, payer rules
- EFFICIENCY: Workflow bottlenecks, manual processes that should be automated
- DATA_QUALITY: Missing fields, mismatches, crosswalk gaps
- BEST_PRACTICE: Industry standards not yet adopted
"""

import logging
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, case, or_

from app.models import db, BillingRecord, EraClaimLine, EraPayment, Payer, InsightLog
from app.revenue.writeoff_filter import not_written_off

logger = logging.getLogger(__name__)

# CARC codes with known fix actions — industry standard denial prevention
PREVENTABLE_CARC = {
    "1": ("Deductible", "Verify patient benefits before service"),
    "2": ("Coinsurance", "Collect estimated coinsurance at time of service"),
    "3": ("Co-payment", "Collect copay at check-in"),
    "4": ("Modifier issue", "Review modifier usage with coders"),
    "16": ("Missing information", "Implement pre-submission claim scrubbing"),
    "18": ("Duplicate claim", "Check for duplicates before submission"),
    "22": ("Coordination of Benefits", "Verify primary/secondary order at registration"),
    "27": ("Expenses after coverage ended", "Real-time eligibility check before service"),
    "29": ("Filing deadline passed", "Automate submission within 48 hours of service"),
    "31": ("Non-covered charge", "Prior authorization check for all advanced imaging"),
    "50": ("Non-covered service", "Check medical necessity before scheduling"),
    "96": ("Non-covered charge", "Prior auth or medical necessity review"),
    "97": ("Payment adjusted: prior payer paid", "Verify COB and post primary ERA before billing secondary"),
    "109": ("Not covered by plan", "Real-time eligibility verification"),
    "119": ("Benefit max reached", "Track patient benefit accumulators"),
    "197": ("Prior auth required", "Implement prior auth tracking system"),
    "204": ("Service not covered", "Eligibility check with benefit details"),
    "242": ("Services not provided", "Documentation improvement program"),
    "B7": ("Provider not certified", "Maintain up-to-date credentialing"),
    "B16": ("New patient restriction", "Verify network status before scheduling"),
}

# Industry benchmarks for radiology practices
BENCHMARKS = {
    "denial_rate_target": 5.0,  # <5% is best-in-class
    "denial_rate_warning": 10.0,  # >10% needs attention
    "days_to_submit": 3,  # Claims should go out within 3 days
    "days_to_appeal": 30,  # Appeals within 30 days of denial
    "secondary_capture_rate": 95.0,  # % of secondary-eligible claims billed
    "clean_claim_rate": 95.0,  # First-pass acceptance rate target
    "ar_days_target": 35,  # Days in A/R target
    "ar_days_warning": 45,  # A/R days warning threshold
    "crosswalk_coverage": 90.0,  # % of billing records with Topaz ID
    "match_rate_target": 95.0,  # ERA-to-billing match rate target
}


def generate_pipeline_suggestions() -> list[dict]:
    """Analyze billing pipeline and generate improvement suggestions.

    Returns a list of suggestion dicts sorted by estimated impact (highest first).
    Each suggestion includes:
      - category, severity, title, description, recommendation
      - estimated_impact ($), affected_count
      - source: "pipeline" (distinguishes from regular recommendations)
      - effort: QUICK_WIN, MODERATE, MAJOR_PROJECT
      - best_practice: industry standard reference
    """
    suggestions = []

    analyzers = [
        _analyze_denial_prevention,
        _analyze_timely_filing,
        _analyze_secondary_capture,
        _analyze_eligibility_gaps,
        _analyze_crosswalk_coverage,
        _analyze_match_rate,
        _analyze_payment_posting,
        _analyze_coding_patterns,
        _analyze_payer_contract_compliance,
        _analyze_workflow_automation,
    ]

    for analyzer in analyzers:
        try:
            results = analyzer()
            suggestions.extend(results)
        except Exception as e:
            logger.warning(f"Pipeline analyzer {analyzer.__name__} failed: {e}")

    # Sort by estimated impact (highest first), then severity
    severity_rank = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    suggestions.sort(key=lambda s: (
        -abs(s.get("estimated_impact") or 0),
        severity_rank.get(s.get("severity", "LOW"), 9),
    ))

    return suggestions


def persist_pipeline_suggestions(suggestions: list[dict]) -> int:
    """Save pipeline suggestions to InsightLog, deduplicating by title."""
    existing_titles = {r[0] for r in db.session.query(InsightLog.title).filter(
        InsightLog.category.like("PIPELINE_%")
    ).all()}

    saved = 0
    for s in suggestions:
        if s["title"] in existing_titles:
            continue
        log = InsightLog(
            category=f"PIPELINE_{s.get('subcategory', 'GENERAL')}",
            severity=s["severity"],
            title=s["title"],
            description=s["description"],
            recommendation=s["recommendation"],
            estimated_impact=s.get("estimated_impact"),
            affected_count=s.get("affected_count"),
            entity_type=s.get("entity_type"),
            entity_id=s.get("entity_id"),
            data={
                "source": "pipeline",
                "effort": s.get("effort"),
                "best_practice": s.get("best_practice"),
                "benchmark": s.get("benchmark"),
                "current_value": s.get("current_value"),
            },
            status="OPEN",
        )
        db.session.add(log)
        saved += 1
        existing_titles.add(s["title"])

    if saved > 0:
        db.session.commit()
    return saved


# ─── Individual Analyzers ───────────────────────────────────────────────


def _analyze_denial_prevention() -> list[dict]:
    """Identify preventable denials using CARC code analysis."""
    results = []

    # Count denials by reason code
    denial_rows = db.session.query(
        EraClaimLine.cas_reason_code,
        func.count(EraClaimLine.id).label("cnt"),
        func.sum(EraClaimLine.billed_amount).label("total_billed"),
    ).filter(
        EraClaimLine.claim_status == "4",
        EraClaimLine.cas_reason_code.isnot(None),
    ).group_by(EraClaimLine.cas_reason_code).order_by(
        func.count(EraClaimLine.id).desc()
    ).all()

    # Total claims for rate calculation
    total_claims = db.session.query(func.count(EraClaimLine.id)).scalar() or 1
    total_denied = sum(r.cnt for r in denial_rows)
    denial_rate = round(total_denied / total_claims * 100, 1) if total_claims > 0 else 0

    # Overall denial rate check
    if denial_rate > BENCHMARKS["denial_rate_warning"]:
        results.append({
            "subcategory": "REVENUE_LEAK",
            "severity": "CRITICAL",
            "title": f"Denial rate {denial_rate}% exceeds industry threshold",
            "description": (
                f"Your denial rate is {denial_rate}% ({total_denied:,} of {total_claims:,} claims). "
                f"Best-in-class radiology practices maintain <{BENCHMARKS['denial_rate_target']}%. "
                f"Each denied claim costs $25-50 in rework labor alone."
            ),
            "recommendation": (
                "1. Implement front-end eligibility verification for every patient\n"
                "2. Add claim scrubbing rules before submission\n"
                "3. Track top 5 denial reasons monthly and create prevention protocols\n"
                "4. Set denial rate KPI target at 5% and review weekly"
            ),
            "estimated_impact": total_denied * 35,
            "affected_count": total_denied,
            "effort": "MAJOR_PROJECT",
            "best_practice": "MGMA benchmark: top-performing radiology practices maintain <5% denial rate",
            "benchmark": BENCHMARKS["denial_rate_target"],
            "current_value": denial_rate,
        })
    elif denial_rate > BENCHMARKS["denial_rate_target"]:
        results.append({
            "subcategory": "REVENUE_LEAK",
            "severity": "HIGH",
            "title": f"Denial rate {denial_rate}% above best-practice target of {BENCHMARKS['denial_rate_target']}%",
            "description": (
                f"Denial rate is {denial_rate}%. Industry leaders achieve <{BENCHMARKS['denial_rate_target']}%. "
                f"Reducing by {denial_rate - BENCHMARKS['denial_rate_target']:.1f}pp would save "
                f"~${int((denial_rate - BENCHMARKS['denial_rate_target']) / 100 * total_claims * 35):,}/year in rework."
            ),
            "recommendation": (
                "Focus on top 3 preventable denial codes. "
                "Implement pre-submission scrubbing for those specific codes."
            ),
            "estimated_impact": (denial_rate - BENCHMARKS["denial_rate_target"]) / 100 * total_claims * 35,
            "affected_count": total_denied,
            "effort": "MODERATE",
            "best_practice": "HFMA: every 1% reduction in denial rate saves ~$35/claim in rework costs",
        })

    # CARC codes where billed charges are NOT recoverable (per user feedback)
    NON_RECOVERABLE_CARC = {"29", "18"}  # Filing deadline passed, Duplicate claim

    # Specific preventable denial codes
    for row in denial_rows[:10]:
        code = row.cas_reason_code
        if code in PREVENTABLE_CARC:
            label, fix = PREVENTABLE_CARC[code]
            billed = float(row.total_billed or 0)
            # CARC 29/18: revenue is lost, not recoverable — impact is $0
            impact = 0 if code in NON_RECOVERABLE_CARC else billed * 0.6
            results.append({
                "subcategory": "REVENUE_LEAK",
                "severity": "HIGH" if row.cnt >= 20 else "MEDIUM",
                "title": f"CARC {code} ({label}): {row.cnt} preventable denials",
                "description": (
                    f"{row.cnt} claims denied with CARC {code} ({label}), "
                    f"representing ${billed:,.0f} in billed charges. "
                    + ("This revenue is NOT recoverable — shown for prevention tracking only." if code in NON_RECOVERABLE_CARC
                       else "This is a preventable denial with a known fix.")
                ),
                "recommendation": fix,
                "estimated_impact": impact,
                "affected_count": row.cnt,
                "entity_type": "DENIAL_CODE",
                "entity_id": code,
                "effort": "QUICK_WIN" if code in ("29", "18", "22") else "MODERATE",
                "best_practice": f"X12 CARC {code}: standard prevention = {fix}",
            })

    return results


def _analyze_timely_filing() -> list[dict]:
    """Check for timely filing risks and suggest automation."""
    results = []
    today = date.today()
    warning_window = today + timedelta(days=30)

    at_risk_count = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline <= warning_window,
        BillingRecord.appeal_deadline >= today,
        or_(
            BillingRecord.denial_status == "DENIED",
            BillingRecord.denial_status == "PENDING",
        ),
    ).scalar() or 0

    past_count = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline < today,
        BillingRecord.denial_status == "DENIED",
    ).scalar() or 0

    if past_count > 0:
        avg = float(db.session.query(
            func.avg(BillingRecord.total_payment)
        ).filter(BillingRecord.total_payment > 0).scalar() or 200)
        results.append({
            "subcategory": "COMPLIANCE",
            "severity": "CRITICAL",
            "title": f"{past_count} claims past filing/appeal deadline — revenue lost",
            "description": (
                f"{past_count} denied claims have passed their appeal deadline. "
                f"This revenue is NOT recoverable — shown as a loss metric. "
                f"Once a deadline passes, the payer has no obligation to pay."
            ),
            "recommendation": (
                "1. Automate appeal deadline tracking with 30/15/7-day alerts\n"
                "2. Assign daily appeal queue to billing staff\n"
                "3. Set up auto-submission for standard appeal letters\n"
                "4. For future: submit claims within 48 hours of service"
            ),
            "estimated_impact": 0,  # Past deadline = not recoverable
            "affected_count": past_count,
            "effort": "QUICK_WIN",
            "best_practice": "HFMA: automate deadline tracking; submit claims within 72 hours of DOS",
        })

    if at_risk_count > 0:
        results.append({
            "subcategory": "COMPLIANCE",
            "severity": "HIGH",
            "title": f"{at_risk_count} claims approaching filing deadline (next 30 days)",
            "description": (
                f"{at_risk_count} denied/pending claims have deadlines in the next 30 days. "
                f"Prioritize these for immediate appeal or resubmission."
            ),
            "recommendation": (
                "Review these claims daily. Sort by deadline (nearest first). "
                "Standard appeal success rate is 50-65% when filed promptly."
            ),
            "estimated_impact": at_risk_count * 150 * 0.55,
            "affected_count": at_risk_count,
            "effort": "QUICK_WIN",
            "best_practice": "AMA: appeal within 30 days of denial for highest overturn rate",
        })

    return results


def _analyze_secondary_capture() -> list[dict]:
    """Identify missed secondary insurance billing opportunities."""
    results = []

    no_secondary = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.primary_payment > 0,
        or_(
            BillingRecord.secondary_payment == 0,
            BillingRecord.secondary_payment.is_(None),
        ),
    ).scalar() or 0

    total_primary = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.primary_payment > 0,
    ).scalar() or 1

    # Industry average: ~15-20% of patients have secondary insurance
    has_secondary = total_primary - no_secondary
    estimated_secondary_eligible = int(total_primary * 0.17)
    gap = estimated_secondary_eligible - has_secondary
    if gap > 0:
        results.append({
            "subcategory": "REVENUE_LEAK",
            "severity": "HIGH",
            "title": f"Estimated {gap:,} claims may be missing secondary billing",
            "description": (
                f"{no_secondary:,} claims have primary payment but no secondary. "
                f"Industry data shows ~17% of imaging patients have secondary coverage. "
                f"Average secondary payment for radiology is $45-85 per claim."
            ),
            "recommendation": (
                "1. Verify secondary insurance at registration for every patient\n"
                "2. Implement real-time eligibility check (270/271 transaction)\n"
                "3. Auto-bill secondary when primary ERA shows patient responsibility\n"
                "4. Cross-reference COB data from primary ERA"
            ),
            "estimated_impact": gap * 55,
            "affected_count": gap,
            "effort": "MODERATE",
            "best_practice": "RBMA: verify secondary insurance at every visit; auto-bill from ERA COB data",
        })

    return results


def _analyze_eligibility_gaps() -> list[dict]:
    """Suggest eligibility verification improvements."""
    results = []

    elig_count = db.session.query(func.count(EraClaimLine.id)).filter(
        EraClaimLine.claim_status == "4",
        EraClaimLine.cas_reason_code.in_(["27", "109", "204", "B16"]),
    ).scalar() or 0

    if elig_count > 5:
        results.append({
            "subcategory": "BEST_PRACTICE",
            "severity": "HIGH",
            "title": f"{elig_count} denials preventable with real-time eligibility verification",
            "description": (
                f"{elig_count} claims were denied for eligibility-related reasons "
                f"(CARC 27/109/204/B16). These are 100% preventable with upfront "
                f"eligibility verification before the patient is scanned."
            ),
            "recommendation": (
                "1. Implement 270/271 eligibility inquiry for every scheduled patient\n"
                "2. Check eligibility 24-48 hours before appointment AND at check-in\n"
                "3. Verify plan effective dates, coverage type, and network status\n"
                "4. Flag patients with expired or terminated coverage before scanning\n\n"
                "ROI: Each eligibility denial costs ~$25 rework + risk of write-off. "
                "Eligibility verification services cost $0.20-0.50 per check."
            ),
            "estimated_impact": elig_count * 150,
            "affected_count": elig_count,
            "effort": "MODERATE",
            "best_practice": "CMS: verify eligibility before every service; CAQH CORE 270/271 standard",
        })

    return results


def _analyze_crosswalk_coverage() -> list[dict]:
    """Check ID crosswalk completeness for matching efficiency."""
    results = []

    total = db.session.query(func.count(BillingRecord.id)).scalar() or 1
    has_topaz = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.topaz_patient_id.isnot(None)
    ).scalar() or 0
    has_pid = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.patient_id.isnot(None)
    ).scalar() or 0

    topaz_pct = round(has_topaz / total * 100, 1)

    if topaz_pct < BENCHMARKS["crosswalk_coverage"]:
        gap = total - has_topaz
        results.append({
            "subcategory": "DATA_QUALITY",
            "severity": "HIGH" if topaz_pct < 70 else "MEDIUM",
            "title": f"Topaz ID coverage at {topaz_pct}% — {gap:,} records missing",
            "description": (
                f"Only {has_topaz:,} of {total:,} billing records have a Topaz ID. "
                f"Without Topaz ID, the matcher falls back to fuzzy name+date matching, "
                f"which is slower and less accurate. Target: >{BENCHMARKS['crosswalk_coverage']}%."
            ),
            "recommendation": (
                "1. Import Topaz patient export file via the Crosswalk tab\n"
                "2. Upload tbl_PatientNotes to map chart numbers to Topaz IDs\n"
                "3. Run the crosswalk propagation after import\n"
                "4. Re-run Force Re-Match All after improving coverage"
            ),
            "estimated_impact": gap * 5,
            "affected_count": gap,
            "effort": "QUICK_WIN",
            "best_practice": "Maintain >90% crosswalk coverage for efficient ERA auto-matching",
            "benchmark": BENCHMARKS["crosswalk_coverage"],
            "current_value": topaz_pct,
        })

    return results


def _analyze_match_rate() -> list[dict]:
    """Check ERA-to-billing match rate."""
    results = []

    total_era = db.session.query(func.count(EraClaimLine.id)).scalar() or 0
    if total_era == 0:
        return results

    matched = db.session.query(func.count(EraClaimLine.id)).filter(
        EraClaimLine.matched_billing_id.isnot(None)
    ).scalar() or 0

    match_rate = round(matched / total_era * 100, 1)
    unmatched = total_era - matched

    if match_rate < BENCHMARKS["match_rate_target"]:
        results.append({
            "subcategory": "EFFICIENCY",
            "severity": "HIGH" if match_rate < 80 else "MEDIUM",
            "title": f"ERA match rate {match_rate}% — {unmatched:,} claims unlinked",
            "description": (
                f"Only {match_rate}% of ERA claims auto-match to billing records. "
                f"Unmatched claims mean payment data isn't flowing to billing records, "
                f"so underpayments and denials may be missed. Target: >{BENCHMARKS['match_rate_target']}%."
            ),
            "recommendation": (
                "1. Check the unmatched claims diagnostics for common failure patterns\n"
                "2. Import more crosswalk data to improve ID-based matching (Pass 0)\n"
                "3. Verify OCMRI import captures both patient name variants (columns A & O)\n"
                "4. Use Force Re-Match All after adding crosswalk data"
            ),
            "estimated_impact": unmatched * 10,
            "affected_count": unmatched,
            "effort": "MODERATE",
            "best_practice": "Target >95% auto-match rate; remaining 5% manual review",
            "benchmark": BENCHMARKS["match_rate_target"],
            "current_value": match_rate,
        })

    return results


def _analyze_payment_posting() -> list[dict]:
    """Identify payment posting gaps."""
    results = []

    zero_count = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.era_claim_id.isnot(None),
        or_(
            BillingRecord.total_payment == 0,
            BillingRecord.total_payment.is_(None),
        ),
        not_written_off(),
    ).scalar() or 0

    if zero_count > 10:
        results.append({
            "subcategory": "DATA_QUALITY",
            "severity": "MEDIUM",
            "title": f"{zero_count} matched claims still show $0 payment",
            "description": (
                f"{zero_count} billing records are linked to ERA data but still show $0 total payment. "
                f"This may indicate the payment amount isn't flowing from ERA to billing, "
                f"or these are denied claims that need follow-up."
            ),
            "recommendation": (
                "1. Review the matched claims list — filter by $0 billing total\n"
                "2. For denied claims: route to appeal queue\n"
                "3. For paid claims with missing amounts: check ERA paid_amount field\n"
                "4. Consider auto-posting ERA paid amounts to billing records"
            ),
            "estimated_impact": zero_count * 50,
            "affected_count": zero_count,
            "effort": "QUICK_WIN",
            "best_practice": "Auto-post ERA payments to billing records within 24 hours of receipt",
        })

    return results


def _analyze_coding_patterns() -> list[dict]:
    """Identify coding improvement opportunities."""
    results = []

    coding_rows = db.session.query(
        EraClaimLine.cas_reason_code,
        func.count(EraClaimLine.id).label("cnt"),
    ).filter(
        EraClaimLine.claim_status == "4",
        EraClaimLine.cas_reason_code.in_(["4", "16", "242", "50"]),
    ).group_by(EraClaimLine.cas_reason_code).all()

    total_coding = sum(r.cnt for r in coding_rows)

    if total_coding > 5:
        results.append({
            "subcategory": "BEST_PRACTICE",
            "severity": "MEDIUM",
            "title": f"{total_coding} denials from coding/documentation issues",
            "description": (
                f"{total_coding} claims denied for modifier problems (CARC 4), "
                f"missing information (CARC 16), documentation (CARC 242), or "
                f"non-covered service (CARC 50). These indicate upstream coding issues."
            ),
            "recommendation": (
                "1. Implement pre-submission claim scrubbing with edit checks\n"
                "2. Review modifier usage patterns quarterly with radiologists\n"
                "3. Create CPT-specific documentation requirements checklist\n"
                "4. Consider coding audit for high-denial-rate procedure codes"
            ),
            "estimated_impact": total_coding * 100,
            "affected_count": total_coding,
            "effort": "MODERATE",
            "best_practice": "ACR: quarterly coding audit + monthly denial reason review with coders",
        })

    return results


def _analyze_payer_contract_compliance() -> list[dict]:
    """Check if payers are paying according to expected rates."""
    results = []

    # Exclude payers where low payment is expected/normal
    # W/C and C2C only refer MRI/CT (no PET/BONE), so lower avg is expected
    # ONE CALL is no longer under contract
    SKIP_CARRIERS = {
        "COMP", "SELF PAY", "SELFPAY", "RESEARCH", "X", "UNKNOWN",
        "W/C", "ONE CALL", "C2C",
    }

    # Modality-aware comparison: compare each payer's avg per-modality
    # against the peer average for that SAME modality, not overall average.
    # This prevents payers who only refer MRI/CT from being unfairly compared
    # against payers who also refer PET ($2500) and BONE ($1800).
    carrier_modality = db.session.query(
        BillingRecord.insurance_carrier,
        BillingRecord.modality,
        func.count(BillingRecord.id).label("claim_count"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
    ).filter(
        BillingRecord.total_payment > 0, not_written_off(),
        ~BillingRecord.insurance_carrier.in_(SKIP_CARRIERS),
        BillingRecord.modality.isnot(None),
    ).group_by(
        BillingRecord.insurance_carrier, BillingRecord.modality
    ).having(func.count(BillingRecord.id) >= 5).all()

    # Build per-modality peer averages
    modality_totals = defaultdict(lambda: {"total_pay": 0.0, "count": 0})
    carrier_data = defaultdict(lambda: {"claims": 0, "weighted_gap": 0.0, "details": []})

    for row in carrier_modality:
        mod = row.modality
        avg_pay = float(row.avg_payment)
        modality_totals[mod]["total_pay"] += avg_pay * row.claim_count
        modality_totals[mod]["count"] += row.claim_count

    modality_avg = {
        mod: vals["total_pay"] / vals["count"]
        for mod, vals in modality_totals.items() if vals["count"] > 0
    }

    for row in carrier_modality:
        mod = row.modality
        avg_pay = float(row.avg_payment)
        peer_avg = modality_avg.get(mod, avg_pay)
        if peer_avg > 0:
            gap = (peer_avg - avg_pay) * row.claim_count
            carrier_data[row.insurance_carrier]["claims"] += row.claim_count
            carrier_data[row.insurance_carrier]["weighted_gap"] += gap
            carrier_data[row.insurance_carrier]["details"].append({
                "modality": mod, "avg": avg_pay, "peer": peer_avg, "n": row.claim_count
            })

    # Flag carriers whose weighted avg is 40%+ below modality-adjusted peer avg
    for carrier, info in carrier_data.items():
        if info["claims"] < 20:
            continue
        weighted_peer = sum(d["peer"] * d["n"] for d in info["details"]) / info["claims"]
        weighted_avg = sum(d["avg"] * d["n"] for d in info["details"]) / info["claims"]
        if weighted_avg < weighted_peer * 0.6:
            results.append({
                "subcategory": "REVENUE_LEAK",
                "severity": "HIGH",
                "title": f"{carrier}: avg payment ${weighted_avg:.0f} — 40%+ below modality-adjusted peer average",
                "description": (
                    f"{carrier} pays an average of ${weighted_avg:.2f} per claim "
                    f"across {info['claims']} claims, while the modality-adjusted peer average is ${weighted_peer:.2f}. "
                    f"This is {(1 - weighted_avg/weighted_peer)*100:.0f}% below peers for the same modalities."
                ),
                "recommendation": (
                    "1. Pull the fee schedule for this payer and compare to CMS rates\n"
                    "2. Review the contract for rate escalation clauses\n"
                    "3. Check if underpayment is systematic or limited to certain CPT codes\n"
                    "4. Consider contract renegotiation or termination if persistently low"
                ),
                "estimated_impact": info["weighted_gap"] * 0.3,
                "affected_count": info["claims"],
                "entity_type": "PAYER",
                "entity_id": carrier,
                "effort": "MAJOR_PROJECT",
                "best_practice": "RBMA: review payer contracts annually; benchmark against Medicare rates",
            })

    return results


def _analyze_workflow_automation() -> list[dict]:
    """Suggest workflow automation opportunities based on data patterns."""
    results = []

    total = db.session.query(func.count(BillingRecord.id)).scalar() or 0
    if total == 0:
        return results

    results.append({
        "subcategory": "EFFICIENCY",
        "severity": "MEDIUM",
        "title": "Implement automated claim status inquiry (276/277)",
        "description": (
            "Automated claim status checks eliminate manual phone calls to payers. "
            "A single status inquiry takes 12-15 minutes by phone vs 2 seconds electronically. "
            f"With {total:,} claims in the system, even checking 10% monthly would save significant staff time."
        ),
        "recommendation": (
            "1. Enroll with clearinghouse for 276/277 claim status transactions\n"
            "2. Auto-check status for claims unpaid after 30 days\n"
            "3. Route stale claims (>45 days) to follow-up queue automatically\n"
            "4. Most clearinghouses offer this for $0.10-0.25 per inquiry"
        ),
        "estimated_impact": total * 0.1 * 5,
        "affected_count": int(total * 0.1),
        "effort": "MODERATE",
        "best_practice": "CAQH CORE: electronic claim status inquiry reduces follow-up time by 85%",
    })

    results.append({
        "subcategory": "EFFICIENCY",
        "severity": "HIGH",
        "title": "Implement check scanning for automated payment posting",
        "description": (
            "Scanning insurance checks and patient payments with OCR can auto-extract "
            "check number, amount, payer name, and patient reference. This data can be "
            "auto-matched to ERA payments and billing records, eliminating manual data entry "
            "and improving the bank reconciliation process. Each manually posted check takes "
            "3-5 minutes; scanning + OCR reduces this to seconds."
        ),
        "recommendation": (
            "1. Set up a check scanner (most desktop scanners work, or use a mobile scan app)\n"
            "2. OCR extracts: check number, amount, payer, date, memo/reference\n"
            "3. Auto-match check amount to ERA 835 payment (trace number or amount+payer)\n"
            "4. Auto-match to billing record via patient name/ID on check memo\n"
            "5. Post matched payments to OCMRI current sheet automatically\n"
            "6. Flag unmatched checks for manual review\n"
            "7. Feed check data directly into bank reconciliation"
        ),
        "estimated_impact": total * 0.15 * 4,
        "affected_count": int(total * 0.15),
        "effort": "MAJOR_PROJECT",
        "best_practice": "HFMA: automated payment posting reduces errors by 90% and posting time by 75%",
    })

    results.append({
        "subcategory": "BEST_PRACTICE",
        "severity": "MEDIUM",
        "title": "Set up ERA/EFT auto-enrollment for all payers",
        "description": (
            "Electronic Remittance Advice (835) and Electronic Funds Transfer eliminate "
            "manual payment posting. Each manual EOB takes 3-5 minutes to post vs "
            "instant auto-posting from ERA files."
        ),
        "recommendation": (
            "1. Enroll with all major payers through CAQH EnrollHub\n"
            "2. Priority: Medicare, Medicaid, BCBS, UHC, Aetna, Cigna\n"
            "3. Set up auto-download of 835 files from clearinghouse\n"
            "4. Auto-import 835 files into this system on receipt"
        ),
        "estimated_impact": total * 0.05 * 3,
        "affected_count": total,
        "effort": "MODERATE",
        "best_practice": "NACHA: ERA/EFT reduces payment posting time by 75% and errors by 90%",
    })

    return results
