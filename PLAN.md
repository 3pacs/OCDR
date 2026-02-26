# OCDR Billing Reconciliation System – Implementation Plan

**Based on:** BUILD_SPEC.md v5.0 | **Date:** 2026-02-24
**Stack:** Python 3.11 + Flask 3.x + SQLite 3 + Bootstrap 5.3 + Chart.js 4.x
**Constraint:** 100% LOCAL – zero cloud, zero internet, zero external APIs

---

## PHASE 0 – Setup & Orientation

Before writing any code:

1. Confirm Python 3.11+ and pip available on target machine
2. Confirm Tesseract OCR 5.x installed (for F-12 OCR feature)
3. Confirm target folder structure: `C:\OCDR\import\`, `C:\OCDR\export\`, `C:\OCDR\backup\`
4. Confirm OCMRI.xlsx is accessible (never commit to git)
5. Clone repo; set up `.env` from `.env.example`

---

## PHASE 1 – Sprint 1 (Foundation + Immediate Revenue Wins)

**Goal:** Working app with data loaded. Identify $150K+ in underpayments immediately.

### F-00 · Project Scaffolding + DB Init (P0-BLOCKER, ~8 hrs)

**Files to create:**
- `app/__init__.py` — Flask app factory with Blueprint registration
- `app/config.py` — Config from `.env` (DB path, export dir, backup dir, etc.)
- `app/models.py` — SQLAlchemy models for all 6 tables
- `migrations/` — Alembic setup (`flask db init`, initial migration)
- `seed_data.py` — Insert 15 payer rows + 8 fee schedule rows
- `requirements.txt` — Pin all dependencies
- `.env.example` — Template with all config keys
- `README.md` — Setup + architecture overview

**Key decisions:**
- Use Flask app factory pattern (`create_app()`)
- One Blueprint per module (`import_engine`, `parser`, `matching`, `revenue`, `analytics`, `core`, `monitor`, `export`, `infra`, `ui`)
- SQLAlchemy ORM + Alembic migrations (not raw SQL) for maintainability
- Single `ocdr.db` SQLite file; path configurable via `.env`

**Acceptance test:** `flask run` starts; GET `/health` returns `{status: "ok", record_count: 0}`

---

### F-01 · Excel Import Engine (P0-BLOCKER, ~16 hrs)

**Files to create:**
- `app/import_engine/excel_importer.py`
- `app/import_engine/__init__.py`

**Implementation steps:**
1. Accept multipart upload OR local file path via `POST /api/import/excel`
2. Open with `openpyxl`, read the "Current" sheet
3. Map each row column-by-column per DATA_SCHEMA (cols A–V)
4. Convert Excel serial dates: `date(1899,12,30) + timedelta(days=serial)`
5. Normalize text: `strip().upper()`; map `YES` → `True`, blank → `False` for gado_used
6. Map `SELFPAY`/`SELF-PAY`/`CASH` → `SELF PAY` (BR-10)
7. Set `is_psma=True` if description contains `PSMA` (BR-02)
8. Compute `appeal_deadline = service_date + payers.filing_deadline_days` (BR-05)
9. Deduplicate on `(patient_name, service_date, scan_type, modality)` — upsert or skip
10. Batch insert 500 rows at a time for performance
11. Return `{imported, skipped, errors, duration_ms}`

**Edge cases:**
- C.A.P records: same patient+date can have CHEST+ABDOMEN+PELVIS — NOT duplicates (BR-01)
- Blank `total_payment` → 0.00; validate `primary + secondary ≈ total`
- Missing `reading_physician` → NULL (not empty string)

---

### F-02 · 835 ERA Parser (P0-BLOCKER, ~24 hrs)

**Files to create:**
- `app/parser/era_835_parser.py`
- `app/parser/__init__.py`
- `tests/test_835_parser.py`

**Implementation steps:**
1. Accept file upload or `{folder_path}` for batch processing
2. Split raw file on `~` delimiter to get segments
3. Parse envelope: `ISA`, `GS`, `ST` (version + control numbers)
4. Parse `BPR` segment: `BPR[02]`=payment amount, `BPR[16]`=payment date, `BPR[01]`=method
5. Parse `TRN` segment: `TRN[02]`=check/EFT number
6. Parse `N1*PR` segment: payer name
7. For each `CLP` (claim):
   - `CLP[01]`=claim_id, `CLP[02]`=status, `CLP[03]`=billed, `CLP[04]`=paid
   - Parse `NM1` for patient name
   - Parse `DTM` for service date
   - Parse `SVC` lines: `SVC[01]`=CPT code
   - Parse `CAS` lines (can be multiple per CLP): group, reason, adjustment amount
8. Insert `era_payments` header row first, then `era_claim_lines` rows with FK
9. Handle multi-SVC and multi-CAS per CLP properly
10. Write unit tests with synthetic 835 fixture files

**Segment reference:**
```
ISA ~ GS ~ ST ~ BPR ~ TRN ~ N1*PR ~ CLP ~ NM1 ~ DTM ~ SVC ~ CAS ~ SE ~ GE ~ IEA
```

---

### F-05 · Underpayment Detector (P1-HIGH, ~12 hrs)

**Files to create:**
- `app/revenue/underpayment_detector.py`
- `templates/underpayments.html`

**Implementation:**
- JOIN `billing_records` + `fee_schedule` on `(modality, insurance_carrier)`
- Fall back to `DEFAULT` payer fee schedule if no carrier-specific rate
- Apply gado premium: if `gado_used=True` and `modality IN ('HMRI','OPEN')`, add $200 to expected (BR-03)
- Apply PSMA rate: if `is_psma=True`, use $8,046 not $2,500 (BR-02)
- Flag: `total_payment > 0 AND total_payment < expected_rate * underpayment_threshold` (BR-11)
- Summary endpoint returns: `{total_flagged, total_variance, by_carrier[], by_modality[]}`
- Expected finding: 55.8% of paid claims flagged, ~$913K gap

---

### F-06 · Timely Filing Deadline Tracker (P1-HIGH, ~8 hrs)

**Files to create:**
- `app/revenue/filing_deadlines.py`
- `templates/filing_deadlines.html`

**Implementation:**
- Query `billing_records WHERE total_payment = 0`
- JOIN `payers` on `insurance_carrier = code` to get `filing_deadline_days`
- Compute: `appeal_deadline = service_date + filing_deadline_days`
- Categorize per BR-05:
  - `PAST_DEADLINE`: `today > appeal_deadline`
  - `WARNING_30DAY`: `today > appeal_deadline - 30 days`
  - `SAFE`: else
- Sort by `days_remaining ASC` (most urgent first)
- Expected finding: 36 PAST_DEADLINE, 8 WARNING

---

### F-20 · Local Backup & Version History (P1-HIGH, ~8 hrs)

**Files to create:**
- `app/infra/backup_manager.py`
- `scripts/install_backup_schedule.bat`

**Implementation:**
- `POST /api/backup/run`: copy `ocdr.db` → `C:\OCDR\backup\ocdr_YYYYMMDD_HHMMSS.db`
- SHA256 hash of backup file stored in backup log
- Retention policy: 7 daily, 4 weekly, 12 monthly (prune on each run)
- Optional: Robocopy to NAS path (if configured in `.env`)
- Windows Task Scheduler install via `schtasks.exe /create`

---

## PHASE 2 – Sprint 2 (Match & Recover)

**Goal:** Match 835 ERA data to billing records. Work 628+ recoverable unpaid claims.

### F-03 · Auto-Match Engine (P1-HIGH, ~20 hrs)

**Files to create:**
- `app/matching/match_engine.py`
- `app/matching/__init__.py`
- `templates/match_review.html`

**Algorithm (BR-09):**
```
composite_score = (0.50 × name_similarity) + (0.30 × date_match) + (0.20 × modality_match)

name_similarity  = rapidfuzz.ratio(normalize(patient_name), normalize(patient_name_835))
date_match       = 1.0 if exact, 0.8 if ±1 day, 0.5 if ±2 days, 0.0 otherwise
modality_match   = 1.0 if exact, 0.0 otherwise
```

**Name normalization:**
- `strip().upper()`
- Remove middle initials
- Handle LAST, FIRST vs FIRST LAST variants

**Routing:**
- `score >= 0.95` → auto-accept, update `billing_records.era_claim_id`, `matched_billing_id`
- `0.80 <= score < 0.95` → queue for manual review (`match_review.html`)
- `score < 0.80` → reject (leave unmatched)

**API:**
- `POST /api/match/run` — full re-run, returns stats
- `GET /api/match/results?status=review` — paginated review queue
- `POST /api/match/confirm/<id>` `{action: accept|reject}` — human confirmation

---

### F-04 · Denial Tracking & Appeal Queue (P1-HIGH, ~16 hrs)

**Files to create:**
- `app/revenue/denial_tracker.py`
- `templates/denial_queue.html`
- `templates/denial_detail.html`

**Implementation:**
- Identify denials: `total_payment = 0 OR era CLP[02] = 4`
- Recoverability score (BR-08): `score = billed_amount × (1 - days_since_service/365)`
- Queue sorted by `recoverability_score DESC` (highest-value, most recent first)
- Status lifecycle: `NULL → DENIED → APPEALED → RESOLVED | WRITTEN_OFF`
- Show `denial_reason_code` from CAS segment with plain-English labels:
  - `CO-4` = Not covered / no auth
  - `CO-16` = Missing/invalid information (front-desk issue)
  - `CO-45` = Charges exceed fee schedule
  - `PR-1` = Deductible
  - `PR-2` = Coinsurance
  - `PR-3` = Copay
- Bulk actions: mark multiple claims as appealed
- Filters: carrier, modality, date range, status
- Expected: 722 $0 claims in queue

---

### F-07 · Secondary Insurance Follow-Up (P1-HIGH, ~10 hrs)

**Files to create:**
- `app/revenue/secondary_followup.py`
- `templates/secondary_queue.html`

**Implementation (BR-04):**
- Query: `primary_payment > 0 AND secondary_payment = 0 AND payers.expected_has_secondary = TRUE`
- Priority order: M/M first (Medi-Cal crossover), then CALOPTIMA
- Allow marking records as `SECONDARY_BILLED` or `SECONDARY_NOT_APPLICABLE`
- Expected: 1,919 claims, estimated $643K missing

---

### F-08 · Duplicate Claim Detector (P2-MEDIUM, ~8 hrs)

**Files to create:**
- `app/revenue/duplicate_detector.py`
- `templates/duplicates.html`

**Implementation:**
- `GROUP BY patient_name, service_date, scan_type, modality HAVING COUNT(*) > 1`
- **Exclude C.A.P exception (BR-01):** filter OUT where `description IN ('C.A.P', 'CAP', 'C.A.P.')` OR where the 3 records for same patient+date are CHEST + ABDOMEN + PELVIS combination
- Side-by-side comparison view for human review
- Allow marking pairs as `LEGITIMATE` (e.g. actual repeat scan)

---

## PHASE 3 – Sprint 3 (Automation & Monitoring)

### F-09 · Payer Contract Monitor & Alerts (P1-HIGH, ~12 hrs)

**Files to create:**
- `app/analytics/payer_monitor.py`
- `templates/payer_dashboard.html`
- `templates/payer_detail.html`

**Implementation (BR-06):**
- Monthly revenue + volume per carrier via SQL GROUP BY
- Compare current month vs AVG of prior 3 months
- Alert if drop exceeds `payers.alert_threshold_pct`
- Color coding: RED (>50% drop), YELLOW (>25% drop), GREEN (stable)
- Known critical alerts to surface:
  - ONE CALL: $123K → $0 (likely contract terminated)
  - W/C: 63% volume decline
  - SELF PAY: 88% volume decline

---

### F-11 · Folder Monitor + Auto-Ingest (P1-HIGH, ~16 hrs)

**Files to create:**
- `app/monitor/folder_watcher.py`
- `app/monitor/__init__.py`

**Implementation:**
- `watchdog` library watching `C:\OCDR\import\`
- File routing by extension:
  - `.835` / `.edi` → F-02 ERA parser
  - `.csv` → F-12 CSV importer
  - `.pdf` → F-12 PDF parser
  - `.xlsx` / `.xls` → F-01 Excel importer
- After processing: move to `/processed/` (success) or `/errors/` (failure)
- Runs in a background thread; configurable poll interval (default 30s)
- Magic byte detection as secondary validation beyond extension

---

### F-12 · CSV/PDF Import Parsers (P2-MEDIUM, ~20 hrs)

**Files to create:**
- `app/import_engine/csv_importer.py`
- `app/import_engine/pdf_importer.py`
- `app/import_engine/ocr_engine.py`

**CSV:** `pandas.read_csv()` + fuzzy header matching to DATA_SCHEMA column names (via `rapidfuzz`)

**PDF (digital):** `pdfplumber.extract_tables()` → map to DATA_SCHEMA

**PDF (scanned OCR):**
- OpenCV preprocessing: grayscale → threshold → deskew
- `pytesseract.image_to_string()`
- Side-by-side review UI for human correction of OCR output

---

## PHASE 4 – Sprint 4 (Reporting & Analytics)

### F-10 · Physician Statement Reconciliation (P2-MEDIUM, ~16 hrs)

**Files to create:**
- `app/revenue/physician_statements.py`
- `templates/statements.html`
- `templates/statement_pdf.html`

**Implementation:**
- Match billing_records to physicians via `reading_physician` or `insurance_carrier`
- Monthly statement generation per physician
- PDF output via `ReportLab` or `WeasyPrint`
- Export to `C:\OCDR\export\statements\`
- Track `OWED vs PAID` per period
- Known amounts: Jhangiani = $30,880 owed; Beach Clinical = $5,000 owed

---

### F-13 · PSMA PET Tracking (P2-MEDIUM, ~6 hrs)

- Flag on import: `is_psma = description LIKE '%PSMA%'`
- Dashboard: PSMA count, revenue, avg reimbursement vs standard PET
- Chart: PSMA vs Standard PET side-by-side bar by year
- 2025 known: 52 scans = $418K

---

### F-16 · Denial Reason Code Analytics (P2-MEDIUM, ~10 hrs)

- Aggregate `era_claim_lines.cas_reason_code`
- Top 10 by frequency + top 10 by dollar amount
- Pareto chart (80/20 rule) using Chart.js
- Interpretation guide: CO-16 = front-desk issue, CO-4 = auth issue

---

### F-17 · Check/EFT Payment Matching (P2-MEDIUM, ~12 hrs)

- Group `era_claim_lines` by parent `era_payments` check/EFT
- Import bank statement CSV: match deposits to ERA checks by amount ±$0.01 and check number
- Flag: unmatched deposits + unmatched ERA checks
- Reconciliation summary report

---

## PHASE 5 – Sprint 5 (Analytics & Excel Bridge)

### F-14 · Gado Contrast Cost Tracking (P2-MEDIUM, ~6 hrs)

- Filter: `gado_used = TRUE`
- Dashboard: claim count (1,916), revenue ($838K), by physician, by year
- Cost analysis: configurable $/dose (default $50 from app config)
- Margin calc: revenue per $1 gado spend
- 99% of gado records are HMRI modality

---

### F-15 · Referring Physician Analytics (P2-MEDIUM, ~10 hrs)

- Top 30+ physicians ranked by total revenue
- Per-physician drilldown: revenue by modality, by year, gado usage, insurance mix
- Volume alert (BR-07): flag if current month < 70% of 3-month avg
- Known: top 10 physicians = 54.9% of total revenue

---

### F-18 · Excel CSV Export Bridge (P2-MEDIUM, ~6 hrs)

- Export `billing_records` to `C:\OCDR\export\master_data.csv` every 15 min
- Column order must match Excel "Current" sheet exactly (22 cols)
- Dates as Excel serial numbers (for Power Query compatibility)
- Background thread with configurable interval; also triggerable via `POST /api/export/trigger`

---

## PHASE 6 – Sprint 6 (Dashboard UI)

### F-19 · Local Dashboard Web UI (P3-LOW, ~16 hrs)

**Files to create:**
- `app/ui/dashboard.py`
- `templates/base.html`
- `templates/dashboard.html`
- `static/css/style.css`
- `static/js/dashboard.js`

**KPI Cards (each calls its `/api/*` endpoint):**
1. Total Revenue (all-time + current month)
2. Unpaid Claims count + total value
3. Underpayment Gap ($)
4. Filing Deadline Alerts (PAST + WARNING counts)
5. Secondary Follow-Up Queue (count + est. value)

**Charts:**
- Revenue by carrier (horizontal bar)
- Monthly revenue trend (line chart, 12-month rolling)
- Denials by reason code (donut/pie)
- PSMA vs Standard PET (grouped bar)

**Behavior:**
- Auto-refresh every 60s via `fetch()` + partial DOM update
- Click any KPI card → navigate to detail page
- Bootstrap 5 responsive grid (works on laptop + tablet)

---

## DEPENDENCY GRAPH

```
F-00 (scaffold)
  ├── F-01 (Excel import)
  │     ├── F-05 (underpayments)
  │     ├── F-06 (filing deadlines)
  │     ├── F-07 (secondary followup)  ─┐
  │     ├── F-08 (duplicates)           │
  │     ├── F-09 (payer monitor)        │
  │     ├── F-13 (PSMA)                 │
  │     ├── F-14 (gado)                 │
  │     ├── F-15 (physician analytics)  │
  │     └── F-18 (CSV export)           │
  ├── F-02 (835 parser)                 │
  │     ├── F-03 (auto-match) ──────────┘
  │     │     └── F-04 (denials)
  │     ├── F-16 (denial analytics)
  │     └── F-17 (payment matching)
  ├── F-10 (physician statements) ← F-01
  ├── F-11 (folder monitor) ← F-01, F-02
  │     └── F-12 (CSV/PDF/OCR parsers)
  ├── F-19 (dashboard) ← ALL
  └── F-20 (backup)
```

---

## KEY BUSINESS RULES SUMMARY

| ID | Rule | Where Implemented |
|----|------|-------------------|
| BR-01 | C.A.P not a duplicate | F-08 duplicate detector |
| BR-02 | PSMA detection + rate | F-01 import, F-05 underpayment |
| BR-03 | Gado +$200 premium | F-05 underpayment |
| BR-04 | Secondary expected for M/M + CALOPTIMA | F-07 |
| BR-05 | Timely filing alert 30-day window | F-06 |
| BR-06 | Payer revenue/volume drop alert | F-09 |
| BR-07 | Physician volume drop alert | F-15 |
| BR-08 | Denial recoverability score | F-04 |
| BR-09 | Auto-match confidence scoring | F-03 |
| BR-10 | SELFPAY normalization on import | F-01 |
| BR-11 | Underpayment detection | F-05 |

---

## KNOWN DATA FINDINGS (from prior analysis)

| Finding | Count/Value | Feature |
|---------|------------|---------|
| Total billing records | 19,936 rows | F-01 |
| Unpaid/denied claims | 722 $0 claims | F-04 |
| Underpaid claims | 55.8% of paid, ~$913K gap | F-05 |
| Past filing deadline | 36 claims | F-06 |
| 30-day filing warning | 8 claims | F-06 |
| Missing secondary payments | 1,919 claims, est. $643K | F-07 |
| PSMA PET scans (2025) | 52 scans = $418K | F-13 |
| Gado contrast scans | 1,916 claims, $838K revenue | F-14 |
| ONE CALL revenue | $123K → $0 (2025) | F-09 |
| Physician owed (Jhangiani) | $30,880 | F-10 |
| Physician owed (Beach) | $5,000 | F-10 |

---

## REQUIREMENTS.TXT (planned)

```
flask>=3.0
flask-sqlalchemy>=3.1
flask-migrate>=4.0          # Alembic wrapper
openpyxl>=3.1               # Excel parsing
xlrd>=2.0                   # Legacy .xls support
rapidfuzz>=3.0              # Fuzzy name matching
watchdog>=4.0               # Folder monitoring
pdfplumber>=0.11            # PDF table extraction
pytesseract>=0.3            # OCR wrapper for Tesseract
opencv-python>=4.9          # Image preprocessing for OCR
pandas>=2.2                 # CSV import
reportlab>=4.1              # PDF statement generation
python-dotenv>=1.0          # .env config loading
gunicorn>=22.0              # Production WSGI (optional)
pywin32>=306                # Windows Service support (Windows only)
```

---

## HIPAA / SECURITY NOTES

- **NEVER commit OCMRI.xlsx** (contains PHI) — add to `.gitignore`
- Use `seed_data.py` with synthetic test data only
- No data leaves local network (zero internet dependency)
- Optional SQLCipher encryption for `ocdr.db` (configure via `.env`)
- NTFS folder permissions restrict `C:\OCDR\` to authorized users
- All API routes are localhost-only (Flask `host='0.0.0.0'` for LAN access, firewalled)

---

## BUILD ORDER CHECKLIST

### Sprint 1 (do first — unblocks everything)
- [ ] F-00: Scaffold + DB + seed data
- [ ] F-20: Backup manager
- [ ] F-01: Excel importer (loads 19,936 rows)
- [ ] F-02: 835 ERA parser
- [ ] F-05: Underpayment detector
- [ ] F-06: Filing deadline tracker

### Sprint 2 (revenue recovery)
- [ ] F-03: Auto-match engine
- [ ] F-04: Denial queue
- [ ] F-07: Secondary follow-up
- [ ] F-08: Duplicate detector

### Sprint 3 (automation)
- [ ] F-09: Payer contract monitor
- [ ] F-11: Folder watcher
- [ ] F-12: CSV/PDF/OCR importers

### Sprint 4 (reporting)
- [ ] F-10: Physician statements
- [ ] F-13: PSMA tracking
- [ ] F-16: Denial analytics
- [ ] F-17: Payment matching

### Sprint 5 (analytics)
- [ ] F-14: Gado analytics
- [ ] F-15: Physician analytics
- [ ] F-18: CSV export bridge

### Sprint 6 (dashboard)
- [ ] F-19: Web dashboard UI
