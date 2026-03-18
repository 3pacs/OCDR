# OCDR — Session Log

## Branch: `claude/billing-reconciliation-system-QOXpY`

---

## OCMRI Excel Column Mapping (Confirmed by User)

The OCMRI.xlsx "Current" sheet has two layouts. The header-based mapping
auto-detects which layout is in use. Both are supported.

### Column positions and what they mean:

| Col | Letter | Old Layout (22-col)      | New Layout (23-col)         |
|-----|--------|--------------------------|-----------------------------|
| 0   | A      | Patient (patient_name)   | Patient (patient_name)      |
| 1   | B      | Doctor                   | Doctor                      |
| 2   | C      | Scan                     | Scan (duplicated w/ R)      |
| 3   | D      | Gado                     | Gado                        |
| 4   | E      | Insurance                | Insurance                   |
| 5   | F      | Type/Modality            | Type/Modality (dupl. w/ Q)  |
| 6   | G      | **Date (service_date)**  | **Date (service_date)**     |
| 7   | H      | Primary payment          | Primary payment             |
| 8   | I      | Secondary payment        | Secondary payment           |
| 9   | J      | Total payment            | Total payment               |
| 10  | K      | Extra charges            | Extra charges               |
| 11  | L      | Read By                  | Read By                     |
| 12  | M      | ID (jacket/chart number) | **Chart ID (patient_id)**   |
| 13  | N      | Birth Date               | Birth Date                  |
| 14  | O      | Patient Name (display)   | Patient Name (display)      |
| 15  | P      | **S Date (schedule_date)**| **S Date (schedule_date)**  |
| 16  | Q      | Modalities               | Modalities                  |
| 17  | R      | Description              | Description                 |
| 18  | S      | Month                    | Month                       |
| 19  | T      | Year                     | Year                        |
| 20  | U      | New                      | New                         |
| 21  | V      | Topaz ID                 | **Patient ID (topaz_patient_id)** |
| 22  | W      | —                        | Payer Group                 |

### Key facts (confirmed by user):
- **G and P are DATES** — not patient names, not IDs. Do not validate/reject them.
- **M is Chart ID** — stored as `patient_id` (the jacket/chart number).
- **V is Patient ID** — stored as `topaz_patient_id`, flows into `topaz_id`.
- **A and O are both patient name** — A is the primary, O is the display name from
  Purview/Candelis. Sometimes they differ (research patients or data entry mistakes).
- **F relates to Q** — both are modality (F = "Type", Q = "Modalities"). Duplicated
  across Candelis and Purview raw data.
- **C relates to R** — both are scan type (C = "Scan", R = "Description"). Also
  duplicated across systems.
- The sheet contains **raw data merged from Candelis and Purview**, so some columns
  are duplicated. The rest is cleaned.

---

## What Was Done (Session 2026-03-07)

### Commit 1: `387d8b0` — Fix datetime vs date comparison error
- **Problem**: `_excel_serial_to_date()` returned `datetime` objects when openpyxl
  gave a `datetime`, but downstream code compared them with `date` objects using
  `<` / `>`. Python's `datetime` is a subclass of `date`, and this caused subtle
  type errors in some comparisons and dedup logic.
- **Fix**: Added `isinstance(serial, date)` check (after the `datetime` check) so
  plain `date` objects pass through. The `datetime` branch calls `.date()` to
  normalize everything to `date`.
- **Files changed**: `backend/app/ingestion/excel_ingestor.py`

### Commit 2: `a52bd59` — (REVERTED) Date validation and month/year derivation
- Added `_date_is_reasonable()` and `_derive_service_date()` to both ingestors.
- **Reverted in commit `d94cda8`** because G and P ARE real date columns — the
  validation was based on a misunderstanding and would have rejected valid dates.

### Commit 3: `d94cda8` — Revert date validation/derivation
- Removed `_date_is_reasonable()` and `_derive_service_date()` from both
  `excel_ingestor.py` and `flexible_excel_ingestor.py`.

### Commit 4: `4dec861` — Rename patient_id_new to topaz_patient_id
- **Problem**: Column V ("Patient ID") was internally mapped to `patient_id_new`,
  which was confusing — it looked like a generic new patient ID field.
- **Fix**: Renamed to `topaz_patient_id` everywhere: header map, parsing logic,
  and extra_data storage. The value still flows into `topaz_id` on the
  BillingRecord when the dedicated "Topaz ID" column is empty.
- **Files changed**: `backend/app/ingestion/excel_ingestor.py`

---

## What Was Done (Session 2026-03-16)

### Commit 5: `6ff9021` — Add CLAUDE.md session log
- Created this file with column mapping, change history, and file reference.

### Commit 6: `f1e81f4` — Add 6 analytics pages (F-08, F-09, F-13, F-14, F-15, F-16)
- **Problem**: The app had 9 working frontend pages but was missing all analytics
  dashboards — Payer Monitor, Physician Analytics, PSMA PET, Gado Contrast,
  Duplicate Detection, and Denial Reason Analytics.
- **Backend**: Created `backend/app/api/routes/analytics_routes.py` with all 6
  feature endpoint groups, registered on `/api/analytics/` prefix.
- **Frontend**: Created 6 new React pages with full chart + table UIs:
  - `PayerMonitor.js` — carrier alerts, revenue trends, drill-down
  - `Physicians.js` — ranked table, top-15 chart, per-doc detail
  - `PSMADashboard.js` — PSMA vs standard PET, yearly trend
  - `GadoDashboard.js` — margin KPIs, by-year/modality, top docs
  - `Duplicates.js` — duplicate groups with C.A.P toggle (BR-01)
  - `DenialAnalytics.js` — Pareto chart, reason codes, by-carrier/modality
- **Navigation**: Reorganized Layout.js nav bar into "Revenue" and "Analytics"
  dropdown menus to keep it clean with 15 total pages.
- **Routing**: Updated App.js with all 6 new routes.

---

## Architecture Notes (IMPORTANT — BUILD_SPEC is outdated)

The BUILD_SPEC.md says **Flask + SQLite**. The actual codebase is:

| Component | Spec Says | Actually Is |
|-----------|-----------|-------------|
| Backend   | Flask 3.x | **FastAPI** (uvicorn, async) |
| Database  | SQLite 3  | **PostgreSQL 16** (asyncpg) |
| Frontend  | Jinja2 + Bootstrap | **React 18** + React Bootstrap + Recharts |
| Charting  | Chart.js  | **Recharts** |
| Deployment| Windows Service | **Docker Compose** (postgres + backend + frontend) |

### How to run:
```bash
docker-compose up
# Backend: http://localhost:8000 (API docs: /docs)
# Frontend: http://localhost:3000
# Postgres: localhost:5432, db=ocmri, user=ocmri, pass=ocmri_secret
```

### Database access (for user):
- **DBeaver** or **pgAdmin** — connect to PostgreSQL at localhost:5432
- **Excel Power Query** — needs PostgreSQL ODBC driver, then Data > From Database > PostgreSQL

---

## Files of Interest

| File | Purpose |
|------|---------|
| `backend/app/ingestion/excel_ingestor.py` | Main OCMRI import engine. Header-based mapping with legacy positional fallback. |
| `backend/app/ingestion/flexible_excel_ingestor.py` | Generic Excel ingestor for non-OCMRI files. Uses dynamic header detection. |
| `backend/app/models/billing.py` | BillingRecord SQLAlchemy model. |
| `backend/app/api/routes/analytics_routes.py` | All 6 analytics endpoints (F-08/09/13/14/15/16). |
| `backend/app/api/routes/revenue_routes.py` | Denial, underpayment, filing, secondary routes. |
| `backend/app/api/routes/insights_routes.py` | Knowledge graph + recommendations. |
| `backend/app/main.py` | FastAPI app factory, router registration, startup migrations. |
| `frontend/src/App.js` | React routing — all 15 pages. |
| `frontend/src/components/Layout.js` | Nav bar with Revenue + Analytics dropdowns. |
| `docker-compose.yml` | 3-service stack: postgres, backend, frontend. |

---

## Feature Completion Status

| Feature | Status | Sprint |
|---------|--------|--------|
| F-00 Scaffolding | DONE | 1 |
| F-01 Excel Import | DONE | 1 |
| F-02 835 ERA Parser | DONE | 1 |
| F-03 Auto-Match Engine | DONE | 2 |
| F-04 Denial Tracking | DONE | 2 |
| F-05 Underpayment Detector | DONE | 1 |
| F-06 Filing Deadlines | DONE | 1 |
| F-07 Secondary Follow-Up | DONE | 2 |
| F-08 Duplicate Detector | **DONE** (session 2026-03-16) | 2 |
| F-09 Payer Monitor | **DONE** (session 2026-03-16) | 3 |
| F-10 Physician Statements | NOT STARTED | 4 |
| F-11 Folder Monitor | PARTIAL (EOB scanner) | 3 |
| F-12 CSV/PDF Import | PARTIAL (stubs) | 3 |
| F-13 PSMA Tracking | **DONE** (session 2026-03-16) | 4 |
| F-14 Gado Analytics | **DONE** (session 2026-03-16) | 5 |
| F-15 Physician Analytics | **DONE** (session 2026-03-16) | 5 |
| F-16 Denial Analytics | **DONE** (session 2026-03-16) | 4 |
| F-17 Payment Reconciliation | NOT STARTED | 4 |
| F-18 CSV Export Bridge | NOT STARTED | 5 |
| F-19 Dashboard UI | DONE | 6 |
| F-20 Backup | DONE | 1 |

## Still TODO / Open Items
- F-10: Physician Statements (PDF generation, monthly invoices)
- F-11: Full folder monitor daemon (watchdog-based)
- F-12: CSV + PDF + OCR import parsers
- F-17: Bank statement reconciliation (check/EFT matching)
- F-18: Scheduled CSV export bridge for Excel Power Query
- User needs to set up DBeaver/pgAdmin for direct database access
- User needs PostgreSQL ODBC driver for Excel Power Query connection

---

## What Was Done (Session 2026-03-17)

### Commit 7: `95de3c4` — Patient search: multi-field support
- **Problem**: Patient lookup only searched by name. User had to spell names perfectly.
- **Fix**: Search now auto-detects what you typed:
  - Digits → searches patient_id (chart number) + topaz_id with partial match
  - Date format (MM/DD/YYYY, YYYY-MM-DD) → searches birth_date
  - Text → name search (case-insensitive, partial, checks both patient_name and
    patient_name_display)
- **Files**: `analytics_routes.py`, `PatientLookup.js`

### Commit 8: `f5208eb` — Overhaul auto-matcher (8 → 11 passes)
- **Problems found**: Passes 5 & 6 compared ERA `paid_amount` against billing
  `total_payment` which is $0 before matching (dead code). patient_name_display
  ignored. No claim_id→patient_id cross-reference. Date window only ±3 days.
  Name-only pass required exactly 1 record per patient.
- **New passes**: P0b (claim_id→patient_id), P4b (±7 days), P6 (name+modality)
- **Fixes**: Amount passes use billed_amount, display name indexed, P8 multi-record
- **Files**: `auto_matcher.py`, `matching_routes.py`

### Commit 9: `6a1ef03` — Leading zeros fix + diagnostic endpoint
- **Problem**: ERA files zero-pad claim_ids ("00061501" vs "61501").
- **Fix**: _strip_leading_zeros() on both sides of comparison.
- **New**: `GET /api/matching/diagnose/{id}` — explains WHY a claim didn't match:
  closest candidates, name scores, date gaps, topaz coverage.
- **Files**: `auto_matcher.py`, `matching_routes.py`

### Commit 10: — Topaz prefix encoding system (THE ROOT CAUSE)
- **Problem**: Topaz encodes billing context as numeric prefix on PatientID:
  - `10061723` = primary insurance billing for patient 61723
  - `20061723` = secondary insurance billing
  - `30061723` = tertiary
  - `70061723` = patient copay
  - To get real PatientID: `MOD(claim_id, 10000000)`
  This affects every cross-reference in tbl_Charges and tbl_Payments, and flows
  into ERA 835 claim_ids. Our matcher was comparing "10061723" to "61723" and
  failing on every prefixed claim.
- **Fix**: Added `_decode_topaz_id()` and `_all_topaz_variants()` — Pass 0 and
  Pass 0b now try all variants: raw, zero-stripped, and prefix-decoded.
  Billing index also stores prefix-decoded variants.
- **Also documented**: Access DB audit findings (ID jumps, mislabeled columns,
  chart numbers sheet = tbl_PatientNotes with swapped columns).

---

## Topaz Access Database Structure (from user audit)

### Prefix Encoding (CRITICAL)
- `MOD(PatientID, 10000000)` extracts real patient ID
- Prefix digit: 1=primary, 2=secondary, 3=tertiary, 7=copay, 8/9=other tiers
- Affects tbl_Charges.PatientID, tbl_Charges.TreatRef, tbl_Payments.PatientID

### Key Tables
| Table | Rows | Notes |
|-------|------|-------|
| tbl_Patients | 61,847 | Clean. Address prefix on newer patients (cosmetic). |
| tbl_Charges | ~500K+ | TreatID sequential with small gaps. PatientID is PREFIXED. |
| tbl_Payments | ~135K+ | DailyID starts at 222444. PatientID is PREFIXED. |
| tbl_Insurance | ~65K+ | ID jump at row 31234 (31236→65622). |
| tbl_PatientNotes | ~985+ | NoteText=chart number for newer patients. THIS is how OCMRI gets chart numbers. |
| tbl_PatientTrack | 48,736 | Stops at PID 48736 — missing newest 13K patients. |
| tbl_FinancialSummary | — | 3 mislabeled columns: E="SecInsDate" is actually Ins ID, F="TreatCount" is unknown pointer. |
| tbl_ReferringPhysicians | 3,513 | Clean, sequential. |
| tbl_DiagnosisCodes | 8,674 | Clean. |

### Known Issues
- tbl_FinancialSummary columns E/F/B/G are mislabeled in Access
- "Chart Numbers" sheet = tbl_PatientNotes with columns A/B swapped
- ID jumps in tbl_Insurance and tbl_Notes are database migration artifacts

---

## What Was Done (Session 2026-03-17, continued)

### Commit 11: — Matcher improvements (11 → 13 passes, name normalization, topaz propagation)
- **Problem**: ~3000+ claims still unmatched despite Topaz prefix decoding. Root causes:
  1. `_normalize_name` was word-order-dependent ("KINLEY SHARON" ≠ "SHARON KINLEY")
     so dictionary-based passes (1, 6, 7, 8) missed name-order mismatches
  2. Billing records matched by name/date (passes 1-8) never got `topaz_id` populated,
     so subsequent claims for the same patient couldn't use fast Pass 0
  3. `era_claim_id` set by previous match runs was not indexed in topaz lookup
  4. Date window capped at ±7 days — billing/ERA dates can differ by weeks
- **Fixes**:
  - `_normalize_name` now sorts tokens alphabetically → order-independent matching
  - `topaz_id` auto-propagated on high-confidence matches (≥0.85) with live index update
  - `era_claim_id` indexed in `billing_by_topaz_id` when topaz_id is not set
  - Added Pass 4c (±14d, name≥90) and Pass 4d (±30d, name≥95)
  - Frontend match results now show all 13 pass counts
- **Files**: `auto_matcher.py`, `matching_routes.py`, `Matching.js`, `CLAUDE.md`

---

## What Was Done (Session 2026-03-18)

### Commit 12: `e096f0b` — Fix stuck loading: disable SQL echo, add timeouts
- SQLAlchemy `echo=True` was logging every SQL statement, killing performance.
- Added 30s axios timeout, 30s PostgreSQL statement_timeout, 15s for recommendations.

### Commit 13: `bf2002a` — Fix matcher: trust ID matches, handle name variants
- Pass 0/0b no longer gate on name score — ID is authoritative.
- Added `token_set_ratio` via `_name_score_pair` for Hispanic/Asian name variants.
- Added Force Re-Match All button (clears + re-runs).

### Commit 14: `dbc5e10` — Add unmatched claim diagnostics
- Matcher returns diagnostic breakdown: index coverage, missing data, 20 sample
  unmatched claims with closest candidate and failure reason.

---

## Data Gotchas Log

Confirmed issues, naming quirks, and matching pitfalls discovered from real
patient data. Each entry is verified against screenshots or source files.
Use this to avoid repeating mistakes.

### Naming / Identity

| # | Gotcha | Example | Impact | Confirmed |
|---|--------|---------|--------|-----------|
| G-01 | **Hispanic married + maiden names** — Same patient has completely different last names across systems. ERA uses insurance-registered name, OCMRI uses clinic-registered name. | ERA: "CENICEROS, CAMERINA" / Billing: "FAVELA DE CEN, CAMERINA" | Pass 0/0b rejected valid ID matches due to name gate. Fixed: ID is now authoritative. | 2026-03-18 |
| G-02 | **Name particles (DE, DEL, VAN, etc.)** — Spanish/Portuguese name particles treated as separate tokens, inflating token count and reducing fuzzy scores. | "FAVELA DE CEN" = 3 tokens vs "CENICEROS" = 1 token | `token_sort_ratio` penalizes extra tokens. Fixed: added `token_set_ratio`. | 2026-03-18 |
| G-03 | **Truncated names** — Some systems truncate at field width limits. The same name appears shortened. | "FAVELA DE CEN" may be truncation of "FAVELA DE CENICEROS" | Partial match only. `token_set_ratio` helps. | 2026-03-18 |
| G-04 | **Column A vs Column O** — Both are patient name, but A comes from Candelis and O from Purview. They can differ for same patient (research patients, data entry). | A: "DOE, JOHN" / O: "DOE, JONATHAN" | Matcher checks both `patient_name` and `patient_name_display`. | 2026-03-16 |

### ID Mapping

| # | Gotcha | Example | Impact | Confirmed |
|---|--------|---------|--------|-----------|
| G-05 | **Topaz prefix encoding** — Topaz prepends billing context digit × 10M to PatientID. | `10061723` = primary billing for patient 61723 | Must MOD 10M to get real patient ID. All passes decode this. | 2026-03-17 |
| G-06 | **Leading zeros in ERA claim_id** — ERA 835 files zero-pad claim IDs. | ERA: "00061501" vs billing topaz_id: "61501" | `_strip_leading_zeros()` on both sides. | 2026-03-17 |
| G-07 | **Chart number ≠ Topaz ID** — Column M (jacket/chart #) is the clinic's internal number. Column V (Topaz ID) is the billing system's number. They are independent. | Chart #: 4523, Topaz ID: 61723 | Must use crosswalk to map between them. No formula. | 2026-03-17 |

### Date Matching

| # | Gotcha | Example | Impact | Confirmed |
|---|--------|---------|--------|-----------|
| G-08 | **Service date vs payment date** — ERA 835 `service_date` can differ from billing `service_date` by days or weeks (date of service vs date billed). | ERA: 2025-01-15 / Billing: 2025-01-10 | Passes 4-4d widen to ±3, ±7, ±14, ±30 days. | 2026-03-17 |
| G-09 | **Excel date serial numbers** — openpyxl sometimes returns dates as serial ints (e.g., 45678) instead of datetime objects. | Raw value: 45678 → 2025-01-15 | `_excel_serial_to_date()` handles conversion. | 2026-03-07 |

### Data Quality

| # | Gotcha | Example | Impact | Confirmed |
|---|--------|---------|--------|-----------|
| G-10 | **OCMRI is merged Candelis + Purview** — Some columns are duplicated across systems (C/R = scan, F/Q = modality). | Both have slightly different values for same patient | We use column C/F as primary, R/Q as fallback. | 2026-03-16 |
| G-11 | **tbl_FinancialSummary mislabeled columns** — Access DB column headers don't match actual data. | Col E labeled "SecInsDate" is actually Insurance ID | Do not trust Access column names in this table. | 2026-03-17 |
| G-12 | **tbl_PatientNotes = chart numbers** — This table maps Topaz patient IDs to chart/jacket numbers via NoteText field. Columns A/B are swapped vs the "Chart Numbers" sheet. | | Only reliable source for crosswalk. | 2026-03-17 |

### Matcher Behavior

| # | Gotcha | Example | Impact | Confirmed |
|---|--------|---------|--------|-----------|
| G-13 | **Re-running matcher gives 0 new** — Matcher only processes claims with `matched_billing_id IS NULL`. Once matched (even wrongly), re-running skips them. | All claims matched → "0 new matches" | Use "Force Re-Match All" to clear and re-run. | 2026-03-18 |
| G-14 | **Many-to-one matching** — Multiple ERA claims can link to the same billing record (original payment, adjustment, secondary payer, appeal). | Primary + secondary + adjustment all point to same billing record | Billing records stay in indexes after first match. | 2026-03-17 |

---

### Adding New Gotchas

When a new data issue is found:
1. Add a row to the appropriate table above with a G-XX number
2. Include a concrete example from real data
3. Note the impact on matching/import
4. Mark confirmed date (ideally with screenshot reference)
5. If a code fix was made, note which commit

Upload screenshots of specific patients and I'll cross-reference against
the database to confirm data matches and add verified entries here.
