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
