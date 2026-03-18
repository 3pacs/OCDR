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
    {
        "title": "Import patient data from OCMRI",
        "description": "Import latest patient records from OCMRI Excel file into the billing system.",
        "category": "DATA_IMPORT", "frequency": "DAILY", "priority": 1, "estimated_minutes": 10,
        "action_steps": """## Import Patient Data from OCMRI

1. Open the OCMRI Excel workbook (OCMRI.xlsx — "Current" sheet)
2. Confirm new rows exist since last import (check latest service_date)
3. Go to **Import** page in the app (`/import`)
4. Upload the OCMRI.xlsx file — the system auto-detects the header layout (22 or 23 column)
5. Review the import summary: new records, duplicates skipped, validation warnings
6. Check for any rows flagged with errors (missing patient name, invalid dates)
7. Resolve errors if any — usually data entry issues in the source Excel

**System notes:** Import uses header-based column mapping. See CLAUDE.md for column mapping details.
Columns G and P are dates. Column M is chart ID, Column V is Topaz patient ID.""",
    },
    {
        "title": "Add latest EOBs",
        "description": "Scan and import latest Explanation of Benefits documents received.",
        "category": "DATA_IMPORT", "frequency": "DAILY", "priority": 1, "estimated_minutes": 15,
        "action_steps": """## Add Latest EOBs

1. Collect all physical EOBs received in today's mail
2. Sort by payer (Medicare, commercial, etc.)
3. Scan EOBs using the office scanner (save as PDF)
4. Go to **Import** page in the app (`/import`)
5. Upload ERA 835 files if received electronically
6. For paper-only EOBs, manually note key info:
   - Patient name, DOS, CPT codes, paid amount, adjustment codes
   - CARC/RARC denial reason codes if claim denied
7. Cross-reference against ERA Payments page (`/era-payments`) to verify electronic versions arrived
8. File physical EOBs in the appropriate payer folder

**Automation tip:** Electronic ERA 835 files auto-parse. Paper EOBs are the bottleneck — push payers to send 835s.""",
    },
    {
        "title": "Post payments to Topaz",
        "description": "Post confirmed payments and adjustments into Topaz billing system.",
        "category": "POSTING", "frequency": "DAILY", "priority": 1, "estimated_minutes": 20,
        "action_steps": """## Post Payments to Topaz

1. Open Topaz billing system
2. Go to **Matching** page in the app (`/matching`) — review newly matched ERA claims
3. For each matched claim with high confidence (>90%):
   - Open the patient in Topaz (use Topaz ID from the match)
   - Post the payment amount, adjustment codes, and check/EFT number
   - If secondary payment, post to the secondary line
4. For partial payments or underpayments:
   - Post what was paid
   - Flag for underpayment review (the app auto-detects these at `/underpayments`)
5. For denied claims:
   - Post the denial with CARC/RARC codes
   - The app auto-queues these at `/denials`
6. Mark posted claims in the ERA Payments page

**Key:** Topaz uses prefix-encoded patient IDs (10XXXXX = primary, 20XXXXX = secondary). See CLAUDE.md G-05.""",
    },
    {
        "title": "Reconcile transactions with bank",
        "description": "Match daily bank transactions against posted payments. Flag discrepancies.",
        "category": "RECONCILIATION", "frequency": "DAILY", "priority": 2, "estimated_minutes": 15,
        "action_steps": """## Reconcile Transactions with Bank

1. Log into bank portal — download today's transaction report
2. Open the app Dashboard (`/`)
3. Compare bank deposits against total payments posted today:
   - Check/EFT deposits should match ERA payment totals
   - Patient copays should match front-desk collection log
4. Flag any discrepancies:
   - Missing deposits (payment posted but not in bank)
   - Unknown deposits (in bank but not matched to any ERA/payment)
   - Amount mismatches (partial deposits, combined checks)
5. For EFT payments: match the trace number from ERA 835 to bank EFT reference
6. Note any outstanding items for follow-up

**Common issues:** Combined payer checks covering multiple patients, split deposits across days.""",
    },
    {
        "title": "Export denial list",
        "description": "Generate and export current denial worklist for follow-up.",
        "category": "DENIALS", "frequency": "DAILY", "priority": 2, "estimated_minutes": 10,
        "action_steps": """## Export Denial List

1. Go to **Denial Queue** page (`/denials`)
2. Review new denials added since yesterday
3. Check appeal deadlines — sort by urgency (closest deadline first)
4. For each new denial:
   - Note the CARC/RARC reason codes
   - Determine if it's correctable (missing info, coding error) vs. clinical (medical necessity)
5. Export the current denial worklist (use browser print/PDF or copy to spreadsheet)
6. Assign follow-up actions to appropriate staff
7. Check **Denial Analytics** (`/denial-analytics`) for trending patterns

**Priority:** Focus on high-dollar denials and those approaching appeal deadline. Medicare = 120 days, most commercial = 60-90 days.""",
    },
    {
        "title": "Review unmatched ERA claims",
        "description": "Check unmatched ERA claims dashboard and resolve any that can be manually matched.",
        "category": "RECONCILIATION", "frequency": "DAILY", "priority": 3, "estimated_minutes": 15,
        "action_steps": """## Review Unmatched ERA Claims

1. Go to **Matching** page (`/matching`)
2. Check the unmatched claims count and diagnostic summary
3. For each unmatched claim, check the diagnosis:
   - **No Topaz ID coverage** → Need to import patient's Topaz ID into crosswalk
   - **Name mismatch** → Check if Hispanic married/maiden name issue (G-01), truncation (G-03)
   - **Date mismatch** → Service date vs billing date gap too wide
   - **No billing record** → Patient may not have been imported yet
4. Try "Force Re-Match All" if new billing data was imported today
5. For persistent mismatches:
   - Use the diagnose endpoint to see closest candidates
   - Manually verify in Topaz if needed
   - Update crosswalk if ID mapping was missing

**See CLAUDE.md Gotchas G-01 through G-14 for common matching pitfalls.**""",
    },
    # --- WEEKLY ---
    {
        "title": "Prepare and make bank deposits",
        "description": "Collect all payments received, prepare deposit slips, and make bank deposits.",
        "category": "BANKING", "frequency": "WEEKLY", "schedule_day": 1, "priority": 1, "estimated_minutes": 30,
        "action_steps": """## Prepare and Make Bank Deposits

1. Collect all checks received during the week (from mail, patient payments, insurance checks)
2. Sort checks by type:
   - Insurance checks (group by payer)
   - Patient copay/coinsurance checks
   - Other payments
3. Prepare deposit slip:
   - List each check with amount
   - Total should match sum of all checks
4. Cross-reference against ERA payments posted this week:
   - Each insurance check should correspond to one or more ERA 835 payments
   - Note the check/EFT number for matching
5. Make physical deposit at the bank
6. Scan deposit receipt
7. Record deposit total in accounting system
8. Verify deposit clears the next business day

**Note:** EFT deposits happen automatically — this task is for physical check deposits.""",
    },
    {
        "title": "Review payer monitor alerts",
        "description": "Check payer monitor for payment trend changes, unusual denial spikes, or underpayment patterns.",
        "category": "ANALYTICS", "frequency": "WEEKLY", "schedule_day": 0, "priority": 2, "estimated_minutes": 20,
        "action_steps": """## Review Payer Monitor Alerts

1. Go to **Payer Monitor** page (`/payer-monitor`)
2. Check for alerts (red/yellow indicators):
   - **Payment trend drops** — any payer paying significantly less than historical average
   - **Denial rate spikes** — sudden increase in denial % for a payer
   - **Underpayment patterns** — systematic underpayment below fee schedule
3. For each alert:
   - Drill down to see affected claims
   - Check if it's a contract issue, coding issue, or payer policy change
   - Document findings
4. Compare current rates against fee schedule (`Payer` table benchmarks)
5. If systematic issues found:
   - Flag for contract renegotiation or payer representative call
   - Check if new prior auth requirements were added
   - Review CARC codes for pattern (e.g., CO-4 = modifier issue)
6. Note any action items for follow-up

**Benchmark:** Industry-standard denial rate < 5%. Underpayment tolerance is set per payer in the system.""",
    },
    {
        "title": "Follow up on pending appeals",
        "description": "Review denied claims under appeal. Send follow-up letters where deadlines approach.",
        "category": "DENIALS", "frequency": "WEEKLY", "schedule_day": 2, "priority": 2, "estimated_minutes": 30,
        "action_steps": """## Follow Up on Pending Appeals

1. Go to **Denial Queue** (`/denials`) — filter by "appealed" status
2. Sort by appeal deadline (closest first)
3. For claims appealed >30 days ago with no response:
   - Call payer to check appeal status
   - Note reference number and expected resolution date
   - Send follow-up letter if needed
4. For claims approaching appeal deadline (<14 days remaining):
   - Escalate — ensure appeal was actually received by payer
   - Request expedited review if possible
   - Prepare second-level appeal if first was denied
5. For newly denied claims not yet appealed:
   - Review denial reason
   - Gather supporting documentation (medical records, prior auth, etc.)
   - Draft and submit appeal letter
6. Update claim status in the system after each action
7. Check **Denial Analytics** (`/denial-analytics`) for appeal success rates by payer

**Key deadlines:** Medicare=120 days, most commercial=60-90 days. Check `/filing-deadlines` for per-payer limits.""",
    },
    # --- BI-WEEKLY ---
    {
        "title": "Process payroll",
        "description": "Run bi-weekly payroll for all staff. Verify hours, deductions, and submit.",
        "category": "PAYROLL", "frequency": "BIWEEKLY", "schedule_day": 4, "priority": 1, "estimated_minutes": 60,
        "action_steps": """## Process Payroll

1. Collect timesheets/time clock data for the pay period
2. Verify hours for all employees:
   - Regular hours
   - Overtime (if applicable)
   - PTO/sick time used
3. Review any payroll adjustments:
   - Bonuses
   - Deductions changes
   - New hires or terminations
4. Calculate gross pay for each employee
5. Verify tax withholdings (federal, state, local)
6. Verify benefit deductions (health insurance, retirement, etc.)
7. Submit payroll through payroll provider
8. Verify direct deposits will process on payday
9. Print/distribute pay stubs
10. File payroll records

**Timing:** Submit payroll by Thursday to ensure Friday direct deposit processing.""",
    },
    {
        "title": "Banking reconciliation (bi-weekly)",
        "description": "Full reconciliation of all bank accounts against billing system records for the past two weeks.",
        "category": "RECONCILIATION", "frequency": "BIWEEKLY", "schedule_day": 4, "priority": 1, "estimated_minutes": 45,
        "action_steps": """## Bi-Weekly Banking Reconciliation

1. Download bank statements for the past 2 weeks (all accounts)
2. Pull payment summary from the app Dashboard (`/`)
3. Reconcile deposits:
   - Match each bank deposit to corresponding payment postings
   - EFT trace numbers should match ERA 835 trace numbers
   - Physical check deposits should match deposit slips
4. Reconcile withdrawals:
   - Verify all outgoing payments (vendor bills, payroll, loan payments)
   - Match against accounts payable records
5. Identify discrepancies:
   - Unmatched deposits → payments not posted yet
   - Unmatched withdrawals → unauthorized or unrecorded expenses
   - Timing differences → items in transit
6. Prepare reconciliation report:
   - Bank balance
   - Less: outstanding checks
   - Plus: deposits in transit
   - Equals: adjusted bank balance (should match book balance)
7. Investigate and resolve any remaining differences

**Goal:** Adjusted bank balance = book balance. Any difference >$1 needs investigation.""",
    },
    # --- MONTHLY ---
    {
        "title": "Pay PET supply bills",
        "description": "Review and pay monthly PET radiopharmaceutical supply invoices. Log purchase amounts and payment dates.",
        "category": "BILLS", "frequency": "MONTHLY", "schedule_day": 1, "priority": 1, "estimated_minutes": 20,
        "action_steps": """## Pay PET Supply Bills

1. Collect PET radiopharmaceutical invoices for the month
2. Verify quantities match delivery receipts:
   - FDG doses received
   - PSMA-11 doses received (if applicable — track separately, higher cost)
   - Any other tracers
3. Cross-reference against scan volume:
   - Go to **PSMA Dashboard** (`/psma`) for PSMA PET count
   - Check billing records for total PET scans this month
4. Verify pricing matches contract rates
5. Process payment (check or EFT)
6. Log payment details:
   - Invoice number, amount, date paid, check/EFT number
   - Per-dose cost for tracking trends
7. File invoice and payment receipt
8. Update supply cost tracking spreadsheet

**Cost tracking:** PSMA tracers are significantly more expensive ($3K-5K/dose vs ~$200/FDG dose). Monitor at `/psma`.""",
    },
    {
        "title": "Pay CT supply bills",
        "description": "Review and pay monthly CT contrast and supply invoices. Log purchase amounts and payment dates.",
        "category": "BILLS", "frequency": "MONTHLY", "schedule_day": 1, "priority": 1, "estimated_minutes": 20,
        "action_steps": """## Pay CT Supply Bills

1. Collect CT contrast and supply invoices for the month
2. Verify quantities match delivery receipts:
   - Iodinated contrast media (Omnipaque, Isovue, etc.)
   - Syringes, tubing, and injector supplies
   - Other CT consumables
3. Cross-reference against scan volume in billing records
4. Verify pricing matches contract rates
5. Process payment (check or EFT)
6. Log payment details:
   - Invoice number, amount, date paid, check/EFT number
7. File invoice and payment receipt
8. Flag any significant price increases for contract review

**Note:** Track contrast usage per scan to monitor waste and identify cost-saving opportunities.""",
    },
    {
        "title": "Pay Gado contrast bills",
        "description": "Review and pay monthly gadolinium contrast supply invoices. Log purchase amounts and payment dates.",
        "category": "BILLS", "frequency": "MONTHLY", "schedule_day": 1, "priority": 1, "estimated_minutes": 20,
        "action_steps": """## Pay Gado Contrast Bills

1. Collect gadolinium contrast invoices for the month
2. Verify quantities match delivery receipts:
   - Gadolinium contrast agent (MultiHance, Dotarem, etc.)
   - MRI-specific supplies
3. Cross-reference against MRI scan volume:
   - Go to **Gado Dashboard** (`/gado`) for gado usage analytics
   - Check billing records for MRI scans with gado this month
4. Verify pricing matches contract rates
5. Process payment (check or EFT)
6. Log payment details:
   - Invoice number, amount, date paid, check/EFT number
   - Per-dose cost for margin tracking
7. File invoice and payment receipt
8. Review gado margin on the Gado Dashboard — target positive margin per contrast scan

**Analytics:** The Gado Dashboard tracks margin KPIs. If margin is negative, review contrast pricing vs reimbursement rates.""",
    },
    {
        "title": "Research billing — Jhangiani",
        "description": "Review and submit monthly research billing for Dr. Jhangiani's studies. Verify protocols and billing codes.",
        "category": "RESEARCH_BILLING", "frequency": "MONTHLY", "schedule_day": 5, "priority": 2, "estimated_minutes": 45,
        "action_steps": """## Research Billing — Jhangiani

1. Pull list of all research patients for Dr. Jhangiani this month:
   - Filter billing records by referring_doctor = "JHANGIANI" or similar
   - Cross-reference against active research protocol list
2. For each research scan:
   - Verify the correct research protocol number
   - Confirm billing codes match the protocol requirements
   - Check if scan is billable to insurance or research account
3. Prepare monthly research billing summary:
   - Number of scans by type (MRI, CT, PET)
   - Total charges
   - Breakdown by protocol
4. Submit billing to the appropriate research account/sponsor
5. Track payment status of previous month's submissions
6. File documentation with research coordinator

**Note:** Research billing has different rules than clinical billing. Some scans are sponsor-paid, some are standard insurance. Verify each protocol's billing instructions.""",
    },
    {
        "title": "Research billing — Beach",
        "description": "Review and submit monthly research billing for Beach Clinical Labs studies.",
        "category": "RESEARCH_BILLING", "frequency": "MONTHLY", "schedule_day": 5, "priority": 2, "estimated_minutes": 45,
        "action_steps": """## Research Billing — Beach Clinical Labs

1. Pull list of all Beach Clinical Labs research scans this month:
   - Filter billing records by insurance_carrier = "BEACH" or referring_doctor association
   - Cross-reference against active Beach protocols
2. For each research scan:
   - Verify the correct study protocol
   - Confirm imaging was performed per protocol specifications
   - Check billing codes match contracted rates
3. Prepare monthly billing submission:
   - Number of scans by type
   - Total charges at contracted rates
   - Supporting documentation (scan reports, protocol compliance)
4. Submit invoice to Beach Clinical Labs
5. Track payment of previous month's invoice (net-30 or per contract terms)
6. Reconcile any payment discrepancies from prior months
7. File all documentation

**Payer setup:** Beach Clinical Labs is configured as a payer in the system (code: "BEACH", 180-day filing deadline).""",
    },
    {
        "title": "All-account bank reconciliation",
        "description": "Complete reconciliation of ALL bank accounts (operating, payroll, savings) against all billing and payment records.",
        "category": "RECONCILIATION", "frequency": "MONTHLY", "schedule_day": 28, "priority": 1, "estimated_minutes": 90,
        "action_steps": """## All-Account Bank Reconciliation (Monthly)

1. Download full monthly statements for ALL accounts:
   - Operating account
   - Payroll account
   - Savings account
   - Any other business accounts
2. For each account, perform full reconciliation:
   - Starting balance + deposits - withdrawals = ending balance
   - Match each transaction to a source document
3. Operating account deep-dive:
   - Total insurance payments received vs total ERA payments posted
   - Total patient payments vs front desk collection log
   - All vendor payments vs AP records
4. Payroll account:
   - Verify payroll transfers match payroll submissions
   - Tax deposits match calculated withholdings
5. Prepare consolidated reconciliation report:
   - All account balances
   - Outstanding items list
   - Aging of outstanding items (>30 days = investigate)
6. Compare total collections against app Dashboard revenue figures
7. Investigate and resolve ALL discrepancies
8. Sign off on reconciliation

**This is the most thorough reconciliation — catches anything the bi-weekly missed. Target: zero unexplained differences.""",
    },
    {
        "title": "SBA loan payment",
        "description": "Make monthly SBA loan payment. Verify amount and confirm posting.",
        "category": "BILLS", "frequency": "MONTHLY", "schedule_day": 15, "priority": 1, "estimated_minutes": 10,
        "action_steps": """## SBA Loan Payment

1. Verify current monthly payment amount (check loan statement or amortization schedule)
2. Confirm payment due date (typically the 15th)
3. Initiate payment:
   - If auto-pay: verify it will process on time
   - If manual: initiate bank transfer or send check
4. Record payment:
   - Principal portion
   - Interest portion
   - Any escrow/fees
5. Verify payment posts to loan account within 2-3 business days
6. Save payment confirmation/receipt
7. Update loan balance tracker

**Important:** Late SBA payments can have serious consequences. Set calendar reminder for the 13th as a safety net.""",
    },
    {
        "title": "Review pipeline improvement suggestions",
        "description": "Review system-generated pipeline improvement suggestions. Prioritize and plan implementation for top items.",
        "category": "ANALYTICS", "frequency": "MONTHLY", "schedule_day": 1, "priority": 2, "estimated_minutes": 30,
        "action_steps": """## Review Pipeline Improvement Suggestions

1. Go to **Pipeline Improvements** page (`/pipeline`)
2. Review the impact summary:
   - Total estimated recoverable revenue
   - Number of critical/high suggestions
   - Quick wins available
3. Filter by "Critical" — address these first:
   - Revenue leaks (money being left on the table)
   - Compliance gaps (risk of audit/penalty)
4. Filter by "Quick Wins" — low effort, high return items
5. For each top suggestion:
   - Read the recommendation and best practice reference
   - Assess feasibility for this month
   - Assign to appropriate staff member
6. Review benchmark comparisons:
   - Where are we vs industry standards?
   - What's the biggest gap?
7. Create action plan for top 3-5 items
8. Schedule implementation tasks
9. Compare with last month's suggestions — did we improve?

**The pipeline analyzer runs daily at 6 AM. Suggestions update automatically as billing data improves.**""",
    },
]


async def seed_business_tasks(session: AsyncSession) -> int:
    """Insert default business tasks if table is empty. Backfill action_steps on existing tasks."""
    existing = await session.execute(select(BusinessTask))
    existing_tasks = {t.title: t for t in existing.scalars().all()}

    if not existing_tasks:
        # Fresh seed
        count = 0
        for t in BUSINESS_TASKS:
            session.add(BusinessTask(**t))
            count += 1
        if count:
            await session.commit()
        return count

    # Backfill action_steps on existing tasks that don't have them
    updated = 0
    for t in BUSINESS_TASKS:
        existing = existing_tasks.get(t["title"])
        if existing and not existing.action_steps and t.get("action_steps"):
            existing.action_steps = t["action_steps"]
            updated += 1
    if updated:
        await session.commit()
    return updated


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
