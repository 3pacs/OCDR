"""Seed data for payers, fee schedules, and business tasks."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.payer import Payer, FeeSchedule
from backend.app.models.business_task import BusinessTask


PAYERS = [
    {"code": "M/M", "display_name": "Medicare/Medicaid", "filing_deadline_days": 365, "expected_has_secondary": True, "alert_threshold_pct": 0.25},
    {"code": "CALOPTIMA", "display_name": "CalOptima Managed Medicaid", "filing_deadline_days": 180, "expected_has_secondary": True, "alert_threshold_pct": 0.25},
    {"code": "FAMILY", "display_name": "Family Health Plan", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "INS", "display_name": "Commercial Insurance (General)", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "VU PHAN", "display_name": "Vu Phan Physician Group", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "W/C", "display_name": "Workers Compensation", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "BEACH", "display_name": "Beach Clinical Labs", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "ONE CALL", "display_name": "One Call Care Management", "filing_deadline_days": 90, "expected_has_secondary": False, "alert_threshold_pct": 0.50},
    {"code": "OC ADV", "display_name": "One Call Advanced", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "SELF PAY", "display_name": "Self Pay / Uninsured", "filing_deadline_days": 9999, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "SELFPAY", "display_name": "Self Pay (alternate code)", "filing_deadline_days": 9999, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "STATE", "display_name": "State Programs", "filing_deadline_days": 365, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "COMP", "display_name": "Complimentary / Charity", "filing_deadline_days": 9999, "expected_has_secondary": False, "alert_threshold_pct": 0.50},
    {"code": "X", "display_name": "Unknown / Unclassified", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.50},
    {"code": "GH", "display_name": "Group Health", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
    {"code": "JHANGIANI", "display_name": "Jhangiani Physician Group", "filing_deadline_days": 180, "expected_has_secondary": False, "alert_threshold_pct": 0.25},
]

FEE_SCHEDULES = [
    {"payer_code": "DEFAULT", "modality": "CT", "expected_rate": 395.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "HMRI", "expected_rate": 750.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "PET", "expected_rate": 2500.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "BONE", "expected_rate": 1800.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "OPEN", "expected_rate": 750.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "DX", "expected_rate": 250.00, "underpayment_threshold": 0.80},
    {"payer_code": "JHANGIANI", "modality": "HMRI", "expected_rate": 950.00, "underpayment_threshold": 0.80},
    {"payer_code": "DEFAULT", "modality": "PET_PSMA", "expected_rate": 8046.00, "underpayment_threshold": 0.80},
]


async def seed_payers(session: AsyncSession) -> int:
    """Insert payer records if they don't already exist. Returns count inserted."""
    existing = await session.execute(select(Payer.code))
    existing_codes = {row[0] for row in existing.fetchall()}
    count = 0
    for p in PAYERS:
        if p["code"] not in existing_codes:
            session.add(Payer(**p))
            count += 1
    if count:
        await session.commit()
    return count


async def seed_fee_schedule(session: AsyncSession) -> int:
    """Insert fee schedule records if they don't already exist. Returns count inserted."""
    existing = await session.execute(select(FeeSchedule.payer_code, FeeSchedule.modality))
    existing_keys = {(row[0], row[1]) for row in existing.fetchall()}
    count = 0
    for f in FEE_SCHEDULES:
        if (f["payer_code"], f["modality"]) not in existing_keys:
            session.add(FeeSchedule(**f))
            count += 1
    if count:
        await session.commit()
    return count


BUSINESS_TASKS = [
    # --- DAILY ---
    {"title": "Import patient data from OCMRI", "description": "Import latest patient records from OCMRI Excel file into the billing system.", "category": "DATA_IMPORT", "frequency": "DAILY", "priority": 1, "estimated_minutes": 10},
    {"title": "Add latest EOBs", "description": "Scan and import latest Explanation of Benefits documents received.", "category": "DATA_IMPORT", "frequency": "DAILY", "priority": 1, "estimated_minutes": 15},
    {"title": "Post payments to Topaz", "description": "Post confirmed payments and adjustments into Topaz billing system.", "category": "POSTING", "frequency": "DAILY", "priority": 1, "estimated_minutes": 20},
    {"title": "Reconcile transactions with bank", "description": "Match daily bank transactions against posted payments. Flag discrepancies.", "category": "RECONCILIATION", "frequency": "DAILY", "priority": 2, "estimated_minutes": 15},
    {"title": "Export denial list", "description": "Generate and export current denial worklist for follow-up.", "category": "DENIALS", "frequency": "DAILY", "priority": 2, "estimated_minutes": 10},
    {"title": "Review unmatched ERA claims", "description": "Check unmatched ERA claims dashboard and resolve any that can be manually matched.", "category": "RECONCILIATION", "frequency": "DAILY", "priority": 3, "estimated_minutes": 15},
    # --- WEEKLY ---
    {"title": "Prepare and make bank deposits", "description": "Collect all payments received, prepare deposit slips, and make bank deposits.", "category": "BANKING", "frequency": "WEEKLY", "schedule_day": 1, "priority": 1, "estimated_minutes": 30},
    {"title": "Review payer monitor alerts", "description": "Check payer monitor for payment trend changes, unusual denial spikes, or underpayment patterns.", "category": "ANALYTICS", "frequency": "WEEKLY", "schedule_day": 0, "priority": 2, "estimated_minutes": 20},
    {"title": "Follow up on pending appeals", "description": "Review denied claims under appeal. Send follow-up letters where deadlines approach.", "category": "DENIALS", "frequency": "WEEKLY", "schedule_day": 2, "priority": 2, "estimated_minutes": 30},
    # --- BI-WEEKLY ---
    {"title": "Process payroll", "description": "Run bi-weekly payroll for all staff. Verify hours, deductions, and submit.", "category": "PAYROLL", "frequency": "BIWEEKLY", "schedule_day": 4, "priority": 1, "estimated_minutes": 60},
    {"title": "Banking reconciliation (bi-weekly)", "description": "Full reconciliation of all bank accounts against billing system records for the past two weeks.", "category": "RECONCILIATION", "frequency": "BIWEEKLY", "schedule_day": 4, "priority": 1, "estimated_minutes": 45},
    # --- MONTHLY ---
    {"title": "Pay PET supply bills", "description": "Review and pay monthly PET radiopharmaceutical supply invoices. Log purchase amounts and payment dates.", "category": "BILLS", "frequency": "MONTHLY", "schedule_day": 1, "priority": 1, "estimated_minutes": 20},
    {"title": "Pay CT supply bills", "description": "Review and pay monthly CT contrast and supply invoices. Log purchase amounts and payment dates.", "category": "BILLS", "frequency": "MONTHLY", "schedule_day": 1, "priority": 1, "estimated_minutes": 20},
    {"title": "Pay Gado contrast bills", "description": "Review and pay monthly gadolinium contrast supply invoices. Log purchase amounts and payment dates.", "category": "BILLS", "frequency": "MONTHLY", "schedule_day": 1, "priority": 1, "estimated_minutes": 20},
    {"title": "Research billing — Jhangiani", "description": "Review and submit monthly research billing for Dr. Jhangiani's studies. Verify protocols and billing codes.", "category": "RESEARCH_BILLING", "frequency": "MONTHLY", "schedule_day": 5, "priority": 2, "estimated_minutes": 45},
    {"title": "Research billing — Beach", "description": "Review and submit monthly research billing for Beach Clinical Labs studies.", "category": "RESEARCH_BILLING", "frequency": "MONTHLY", "schedule_day": 5, "priority": 2, "estimated_minutes": 45},
    {"title": "All-account bank reconciliation", "description": "Complete reconciliation of ALL bank accounts (operating, payroll, savings) against all billing and payment records.", "category": "RECONCILIATION", "frequency": "MONTHLY", "schedule_day": 28, "priority": 1, "estimated_minutes": 90},
    {"title": "SBA loan payment", "description": "Make monthly SBA loan payment. Verify amount and confirm posting.", "category": "BILLS", "frequency": "MONTHLY", "schedule_day": 15, "priority": 1, "estimated_minutes": 10},
    {"title": "Review pipeline improvement suggestions", "description": "Review system-generated pipeline improvement suggestions. Prioritize and plan implementation for top items.", "category": "ANALYTICS", "frequency": "MONTHLY", "schedule_day": 1, "priority": 2, "estimated_minutes": 30},
]


async def seed_business_tasks(session: AsyncSession) -> int:
    """Insert default business tasks if table is empty."""
    existing = await session.execute(select(BusinessTask.id))
    if existing.first():
        return 0  # Already seeded

    count = 0
    for t in BUSINESS_TASKS:
        session.add(BusinessTask(**t))
        count += 1
    if count:
        await session.commit()
    return count


async def run_all_seeds(session: AsyncSession) -> dict:
    """Run all seed operations."""
    payers_count = await seed_payers(session)
    fees_count = await seed_fee_schedule(session)
    tasks_count = await seed_business_tasks(session)
    return {
        "payers_inserted": payers_count,
        "fee_schedules_inserted": fees_count,
        "business_tasks_inserted": tasks_count,
    }
