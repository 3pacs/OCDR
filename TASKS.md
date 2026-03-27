# TASKS.md — Business Task Log

> Auto-generated: 2026-03-19T20:38:54.397853Z
> This file is updated whenever tasks change. LLMs: read this to understand current operational state.

## Today's Checklist (2026-03-19)

**Progress: 0/9 completed**

- [ ] **Review today's scan schedule** *(15min)*
- [ ] **Import patient data from OCMRI** *(10min)*
- [ ] **Add latest EOBs** *(15min)*
- [ ] **Post payments to Topaz** *(20min)*
- [ ] **Verify posted payments (post checks)** *(15min)*
- [ ] **Reconcile transactions with bank** *(15min)*
- [ ] **Export denial list** *(10min)*
- [ ] **Review unmatched ERA claims** *(15min)*
- [ ] **AI daily system review** *(10min)*

## Recent History (7 days)

### 2026-03-19 — 0/9 completed
- [PENDING] Verify posted payments (post checks)
- [PENDING] Post payments to Topaz
- [PENDING] Add latest EOBs
- [PENDING] Import patient data from OCMRI
- [PENDING] Review today's scan schedule
- [PENDING] Export denial list
- [PENDING] Reconcile transactions with bank
- [PENDING] AI daily system review
- [PENDING] Review unmatched ERA claims

---

## Task Runbooks (Action Steps)

Detailed step-by-step instructions for each recurring task.
LLMs: use these to guide the user through task completion.

### Daily Tasks

#### Review today's scan schedule [ACTIVE]

*Pull today's scan schedule, verify insurance eligibility, flag issues before patients arrive.*

- **Category:** DATA_IMPORT
- **Priority:** 1 (Urgent)
- **Estimated time:** 15 minutes

## Review Today's Scan Schedule

Do this first thing in the morning before patients start arriving.

### Steps
1. Open Candelis/Purview scheduling system
2. Print or export today's schedule
3. Verify insurance eligibility for each patient
4. Confirm prior authorizations for MRI, PET/CT, CT with contrast
5. Flag any patients with missing auth or insurance issues
6. Verify correct CPT codes are queued
7. Check for open slots that could accommodate add-on patients

---

#### Import patient data from OCMRI [ACTIVE]

*Import latest patient records from OCMRI Excel file into the billing system.*

- **Category:** DATA_IMPORT
- **Priority:** 1 (Urgent)
- **Estimated time:** 10 minutes

## Import Patient Data from OCMRI

1. Open the OCMRI Excel workbook (OCMRI.xlsx - Current sheet)
2. Confirm new rows exist since last import
3. Go to Import page (/import)
4. Upload the OCMRI.xlsx file
5. Review import summary: new records, duplicates skipped, validation warnings
6. Check for any rows flagged with errors

---

#### Add latest EOBs [ACTIVE]

*Scan and import latest Explanation of Benefits documents received.*

- **Category:** DATA_IMPORT
- **Priority:** 1 (Urgent)
- **Estimated time:** 15 minutes

## Add Latest EOBs

1. Collect all physical EOBs received in today's mail
2. Sort by payer
3. Scan EOBs (save as PDF)
4. Upload ERA 835 files if received electronically
5. For paper-only EOBs, manually note key info
6. Cross-reference against ERA Payments page
7. File physical EOBs

---

#### Post payments to Topaz [ACTIVE]

*Post confirmed payments and adjustments into Topaz billing system.*

- **Category:** POSTING
- **Priority:** 1 (Urgent)
- **Estimated time:** 20 minutes

## Post Payments to Topaz

1. Open Topaz billing system
2. Go to Matching page - review newly matched ERA claims
3. For each matched claim with high confidence (>90%), post payment
4. For partial payments or underpayments, flag for review
5. For denied claims, post with CARC/RARC codes
6. Mark posted claims in ERA Payments page

---

#### Verify posted payments (post checks) [ACTIVE]

*After posting to Topaz, verify payments posted correctly. Catch errors before they compound.*

- **Category:** POSTING
- **Priority:** 1 (Urgent)
- **Estimated time:** 15 minutes

## Verify Posted Payments

1. Pull today's posting batch total from Topaz
2. Compare against ERA 835 payment totals
3. Spot check 3-5 random patients
4. Verify secondary insurance triggers
5. Check denial postings
6. Review zero-pay / adjustment-only claims
7. Update daily posting log

---

#### Reconcile transactions with bank [ACTIVE]

*Match daily bank transactions against posted payments. Flag discrepancies.*

- **Category:** RECONCILIATION
- **Priority:** 2 (High)
- **Estimated time:** 15 minutes

## Reconcile Transactions with Bank

1. Log into bank portal - download today's transaction report
2. Compare bank deposits against total payments posted
3. Match EFT trace numbers from ERA 835 to bank references
4. Flag any discrepancies
5. Note outstanding items for follow-up

---

#### Export denial list [ACTIVE]

*Generate and export current denial worklist for follow-up.*

- **Category:** DENIALS
- **Priority:** 2 (High)
- **Estimated time:** 10 minutes

## Export Denial List

1. Go to Denial Queue page (/denials)
2. Review new denials added since yesterday
3. Check appeal deadlines - sort by urgency
4. Determine if correctable vs clinical denial
5. Export current denial worklist
6. Assign follow-up actions
7. Check Denial Analytics for trending patterns

---

#### Review unmatched ERA claims [ACTIVE]

*Check unmatched ERA claims and resolve manually matchable ones.*

- **Category:** RECONCILIATION
- **Priority:** 3 (Normal)
- **Estimated time:** 15 minutes

## Review Unmatched ERA Claims

1. Go to Matching page (/matching)
2. Check unmatched claims count
3. For each unmatched claim, check diagnosis
4. Try Force Re-Match if new billing data was imported
5. For persistent mismatches, verify in Topaz and update crosswalk

---

#### AI daily system review [ACTIVE]

*End-of-day: run daily review to check data quality, match rates, denial trends, and log findings.*

- **Category:** ANALYTICS
- **Priority:** 3 (Normal)
- **Estimated time:** 10 minutes

## AI Daily System Review

Go to Tasks page and click Run Review, or open Claude Code and type: run daily review

Checks: data quality, match rate, denial trends, revenue pulse, pipeline suggestions delta, system health.

---

### Weekly Tasks

#### Prepare and make bank deposits [ACTIVE] (every Tue)

*Collect all payments received, prepare deposit slips, and make bank deposits.*

- **Category:** BANKING
- **Priority:** 1 (Urgent)
- **Estimated time:** 30 minutes

## Prepare and Make Bank Deposits

1. Collect all checks received during the week
2. Sort by type (insurance, patient copay, other)
3. Prepare deposit slip
4. Cross-reference against ERA payments
5. Make physical deposit
6. Scan deposit receipt
7. Record deposit total

---

#### Review payer monitor alerts [ACTIVE] (every Mon)

*Check payer monitor for payment trend changes and denial spikes.*

- **Category:** ANALYTICS
- **Priority:** 2 (High)
- **Estimated time:** 20 minutes

## Review Payer Monitor Alerts

1. Go to Payer Monitor page (/payers)
2. Check for payment trend drops, denial rate spikes, underpayment patterns
3. Drill down on alerts
4. Compare rates against fee schedule benchmarks
5. Flag systematic issues for contract renegotiation

---

#### Follow up on pending appeals [ACTIVE] (every Wed)

*Review denied claims under appeal. Send follow-up letters where deadlines approach.*

- **Category:** DENIALS
- **Priority:** 2 (High)
- **Estimated time:** 30 minutes

## Follow Up on Pending Appeals

1. Go to Denial Queue - filter by appealed status
2. Sort by appeal deadline
3. Call payers for appeals >30 days with no response
4. Escalate claims approaching deadline (<14 days)
5. Draft and submit appeal letters for new denials
6. Update claim status after each action

---

### Bi-Weekly Tasks

#### Process payroll [ACTIVE] (every other Fri)

*Run bi-weekly payroll for all staff.*

- **Category:** PAYROLL
- **Priority:** 1 (Urgent)
- **Estimated time:** 60 minutes

## Process Payroll

1. Collect timesheets
2. Verify hours, overtime, PTO
3. Review adjustments
4. Calculate gross pay
5. Verify withholdings and deductions
6. Submit payroll
7. Verify direct deposits
8. Print/distribute pay stubs

---

#### Banking reconciliation (bi-weekly) [ACTIVE] (every other Fri)

*Full reconciliation of all bank accounts against billing system records.*

- **Category:** RECONCILIATION
- **Priority:** 1 (Urgent)
- **Estimated time:** 45 minutes

## Bi-Weekly Banking Reconciliation

1. Download bank statements for past 2 weeks
2. Pull payment summary from Dashboard
3. Reconcile deposits (EFT trace numbers, physical checks)
4. Reconcile withdrawals
5. Identify discrepancies
6. Prepare reconciliation report
7. Investigate and resolve differences

---

### Monthly Tasks

#### Pay PET supply bills [ACTIVE] (day 1)

*Review and pay monthly PET radiopharmaceutical supply invoices.*

- **Category:** BILLS
- **Priority:** 1 (Urgent)
- **Estimated time:** 20 minutes

## Pay PET Supply Bills

1. Collect PET radiopharmaceutical invoices
2. Verify quantities match delivery receipts (FDG, PSMA-11)
3. Cross-reference against scan volume (see /psma)
4. Verify pricing matches contract
5. Process payment
6. Log payment details

---

#### Pay CT supply bills [ACTIVE] (day 1)

*Review and pay monthly CT contrast and supply invoices.*

- **Category:** BILLS
- **Priority:** 1 (Urgent)
- **Estimated time:** 20 minutes

## Pay CT Supply Bills

1. Collect CT contrast and supply invoices
2. Verify quantities match delivery receipts
3. Cross-reference against scan volume
4. Verify pricing
5. Process payment
6. Log payment details

---

#### Pay Gado contrast bills [ACTIVE] (day 1)

*Review and pay monthly gadolinium contrast supply invoices.*

- **Category:** BILLS
- **Priority:** 1 (Urgent)
- **Estimated time:** 20 minutes

## Pay Gado Contrast Bills

1. Collect gadolinium contrast invoices
2. Verify quantities match delivery receipts
3. Cross-reference against MRI scan volume (see /gado)
4. Verify pricing
5. Process payment
6. Log payment details and per-dose cost

---

#### All-account bank reconciliation [ACTIVE] (day 28)

*Complete reconciliation of ALL bank accounts against all billing and payment records.*

- **Category:** RECONCILIATION
- **Priority:** 1 (Urgent)
- **Estimated time:** 90 minutes

## All-Account Bank Reconciliation (Monthly)

1. Download full monthly statements for ALL accounts
2. Perform full reconciliation for each account
3. Operating account deep-dive
4. Payroll account verification
5. Prepare consolidated reconciliation report
6. Compare total collections against Dashboard revenue
7. Investigate and resolve ALL discrepancies

---

#### SBA loan payment [ACTIVE] (day 15)

*Make monthly SBA loan payment.*

- **Category:** BILLS
- **Priority:** 1 (Urgent)
- **Estimated time:** 10 minutes

## SBA Loan Payment

1. Verify current monthly payment amount
2. Confirm payment due date
3. Initiate payment
4. Record principal, interest, and fees
5. Verify payment posts within 2-3 business days

---

#### Research billing - Jhangiani [ACTIVE] (day 5)

*Review and submit monthly research billing for Dr. Jhangiani studies.*

- **Category:** RESEARCH_BILLING
- **Priority:** 2 (High)
- **Estimated time:** 45 minutes

## Research Billing - Jhangiani

1. Pull list of research patients for Dr. Jhangiani this month
2. Verify correct research protocol numbers
3. Confirm billing codes match protocol
4. Prepare monthly research billing summary
5. Submit billing to research account/sponsor
6. Track payment of prior submissions

---

#### Research billing - Beach [ACTIVE] (day 5)

*Review and submit monthly research billing for Beach Clinical Labs.*

- **Category:** RESEARCH_BILLING
- **Priority:** 2 (High)
- **Estimated time:** 45 minutes

## Research Billing - Beach Clinical Labs

1. Pull list of Beach Clinical Labs research scans
2. Verify study protocols
3. Check billing codes match contracted rates
4. Prepare monthly billing submission
5. Submit invoice to Beach Clinical Labs
6. Track payment of prior invoices

---

#### Review pipeline improvement suggestions [ACTIVE] (day 1)

*Review system-generated pipeline improvement suggestions and plan implementation.*

- **Category:** ANALYTICS
- **Priority:** 2 (High)
- **Estimated time:** 30 minutes

## Review Pipeline Improvement Suggestions

1. Go to Pipeline Improvements page (/pipeline)
2. Review impact summary
3. Address Critical items first
4. Filter Quick Wins for low-effort high-return items
5. Create action plan for top 3-5 items
6. Compare with last month's suggestions

---

## Pipeline Improvement Notes

User notes and status updates on pipeline improvement suggestions.
LLMs: use these to understand what improvements have been acknowledged, are in progress, or resolved.

#### [OPEN] C2C: avg payment $293 — 40%+ below peer average [OPEN]

- **Severity:** HIGH
- **Impact:** $32,161

#### [OPEN] COMP: avg payment $52 — 40%+ below peer average [OPEN]

- **Severity:** HIGH
- **Impact:** $43,971

#### [OPEN] ERA match rate 69.3% — 1,854 claims unlinked [OPEN]

- **Severity:** HIGH
- **Impact:** $18,540

#### [OPEN] Implement check scanning for automated payment posting [OPEN]

- **Severity:** HIGH
- **Impact:** $22,184

#### [OPEN] ONE CALL: avg payment $251 — 40%+ below peer average [OPEN]

- **Severity:** HIGH
- **Impact:** $109,657

#### [OPEN] Topaz ID coverage at 0.0% — 36,973 records missing [OPEN]

- **Severity:** HIGH
- **Impact:** $184,865

#### [OPEN] Implement automated claim status inquiry (276/277) [OPEN]

- **Severity:** MEDIUM
- **Impact:** $18,486

#### [OPEN] Set up ERA/EFT auto-enrollment for all payers [OPEN]

- **Severity:** MEDIUM
- **Impact:** $5,546
