# OCDR Billing Reconciliation System – Complete Build Specification

**Version:** 6.0 | **Updated:** 2026-02-26 | **Stack:** Python Flask + SQLite + Bootstrap 5
**Constraint:** 100% LOCAL – zero cloud, zero internet, zero external APIs

---

## TABLE OF CONTENTS
1. [Project Metadata](#project-metadata)
2. [Data Schema](#data-schema)
3. [Database Schema](#database-schema)
4. [Features & Build Tickets](#features--build-tickets)
5. [API Routes](#api-routes)
6. [File Structure](#file-structure)
7. [Sprint Plan](#sprint-plan)
8. [Seed Data – Payer Configuration](#seed-data--payer-configuration)
9. [Seed Data – Fee Schedule](#seed-data--fee-schedule)
10. [Business Rules](#business-rules)

---

## PROJECT METADATA

| Key | Value |
|-----|-------|
| **App Name** | OCDR Billing Reconciliation System |
| **Language** | Python 3.11+ |
| **Framework** | Flask 3.x |
| **Database** | SQLite 3 (single file: `ocdr.db`) |
| **Frontend** | Bootstrap 5.3 + Chart.js 4.x + Jinja2 templates |
| **Hosting** | `localhost:5000` (Windows Service via pywin32 or NSSM). LAN access via machine IP. ZERO internet. |
| **OCR Engine** | Tesseract OCR 5.x + OpenCV 4.x (local install, no API) |
| **Security** | PHI data – HIPAA compliant. No data leaves local network. Optional SQLCipher encryption. NTFS folder permissions. |
| **Excel Bridge** | Export CSV to `C:\OCDR\export\` every 15 min. Excel Power Query auto-refreshes from that folder. |

---

## DATA SCHEMA – Excel Source Columns (Current Sheet)

| Col | Name | DB Field | Data Type | Nullable | Sample | Import Rule | Notes |
|-----|------|----------|-----------|----------|--------|-------------|-------|
| A | Patient | patient_name | TEXT | NO | COPE, CURTIS | strip() + upper() | LAST, FIRST format. Primary key component. |
| B | Doctor | referring_doctor | TEXT | NO | VU, KHAI | strip() + upper() | Referring physician. LAST, FIRST or facility name. |
| C | Scan | scan_type | TEXT | NO | ABDOMEN | strip() + upper() | Body part: ABDOMEN, CHEST, HEAD, CERVICAL, LUMBAR, PELVIS, SINUS, etc. |
| D | Gado | gado_used | BOOLEAN | YES | YES | YES=True, else False | Gadolinium contrast. YES or blank. Map blank/empty to FALSE. |
| E | Insurance | insurance_carrier | TEXT | NO | M/M | strip() + upper() | Payer code: M/M, CALOPTIMA, FAMILY, INS, W/C, VU PHAN, JHANGIANI, BEACH, ONE CALL, OC ADV, SELF PAY, STATE, COMP, X, GH |
| F | Type | modality | TEXT | NO | CT | strip() + upper() | Imaging modality: CT, PET, HMRI, BONE, OPEN, DX, GH |
| G | Date | service_date | DATE | NO | 44929 | xlrd.xldate_as_datetime() | Excel serial date. Convert: date(1899,12,30) + serial_days. |
| H | Primary | primary_payment | DECIMAL(10,2) | YES | 220.76 | float or 0.00 | Primary insurance payment amount. Blank = no primary. |
| I | Secondary | secondary_payment | DECIMAL(10,2) | YES | 45.99 | float or 0.00 | Secondary insurance payment. Blank = no secondary. |
| J | Total | total_payment | DECIMAL(10,2) | NO | 226.26 | float, assert H+I=J | Total collected. Should = Primary + Secondary. $0 = unpaid/denied. |
| K | Extra | extra_charges | DECIMAL(10,2) | YES | 0 | float or 0.00 | Additional charges beyond base. Usually 0. |
| L | ReadBy | reading_physician | TEXT | YES | | strip() + upper() | Radiologist who read the study. Different from referring doctor. |
| M | ID | patient_id | INTEGER | YES | 61998 | int | Internal patient ID number. |
| N | Birth Date | birth_date | INTEGER | YES | 16648 | xlrd.xldate_as_datetime() | Excel serial date of patient DOB. |
| O | Patient Name | patient_name_display | TEXT | YES | COPE, CURTIS | ignore if col A populated | Duplicate of col A in some rows. Use col A as canonical. |
| P | S Date | schedule_date | DATE | YES | 44929 | xlrd.xldate_as_datetime() | Schedule date. Usually matches service_date. |
| Q | Modalities | modality_code | TEXT | YES | SR/CT | strip() + upper() | DICOM modality code: MR, CT, SR/CT, NM, DX, etc. |
| R | Description | description | TEXT | YES | C.A.P | strip() | Scan description. C.A.P = Chest/Abdomen/Pelvis (3 scans, 1 visit). CSP = Cervical Spine. |
| S | Month | service_month | TEXT | YES | Jan | derive from service_date | 3-letter month abbreviation derived from col G. |
| T | Year | service_year | TEXT | YES | 2023 | derive from service_date | 4-digit year derived from col G. Used for YoY analysis. |
| U | New | is_new_patient | BOOLEAN | YES | | parse as bool | New patient flag. Rarely populated. |
| V | (empty) | reserved | TEXT | YES | | skip | Unused column 22. |

---

## DATABASE SCHEMA – SQLite Tables

### Table: billing_records
| Column | Type | Constraints | References | Description | Indexed |
|--------|------|-----------|-----------|-------------|---------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | | Internal row ID | YES |
| patient_name | TEXT | NOT NULL | | LAST, FIRST format | YES |
| referring_doctor | TEXT | NOT NULL | physicians.name | Referring physician | YES |
| scan_type | TEXT | NOT NULL | | Body part: ABDOMEN, CHEST, HEAD, etc. | YES |
| gado_used | BOOLEAN | DEFAULT FALSE | | Gadolinium contrast used | NO |
| insurance_carrier | TEXT | NOT NULL | payers.code | Payer code: M/M, CALOPTIMA, etc. | YES |
| modality | TEXT | NOT NULL | | CT, PET, HMRI, BONE, OPEN, DX | YES |
| service_date | DATE | NOT NULL | | Date of service | YES |
| primary_payment | DECIMAL(10,2) | DEFAULT 0 | | Primary insurance payment | NO |
| secondary_payment | DECIMAL(10,2) | DEFAULT 0 | | Secondary insurance payment | NO |
| total_payment | DECIMAL(10,2) | DEFAULT 0 | | Total collected (primary + secondary) | YES |
| extra_charges | DECIMAL(10,2) | DEFAULT 0 | | Additional charges | NO |
| reading_physician | TEXT | | | Radiologist who read the study | NO |
| patient_id | INTEGER | | | Internal patient ID | YES |
| birth_date | DATE | | | Patient DOB (from Excel col N, serial date) | NO |
| schedule_date | DATE | | | Schedule date (from Excel col P, usually matches service_date) | NO |
| modality_code | TEXT | | | DICOM modality code: MR, CT, SR/CT, NM, DX (from Excel col Q) | NO |
| description | TEXT | | | Scan description (C.A.P, CSP, etc.) | NO |
| is_new_patient | BOOLEAN | DEFAULT FALSE | | New patient flag (from Excel col U, rarely populated) | NO |
| is_psma | BOOLEAN | DEFAULT FALSE | | PSMA PET flag. Derive from description LIKE '%PSMA%' | YES |
| cap_exception | BOOLEAN | DEFAULT FALSE | | TRUE if this record is part of a C.A.P multi-scan visit (not a duplicate) | NO |
| denial_status | TEXT | DEFAULT NULL | | NULL=not denied, DENIED, APPEALED, RESOLVED, WRITTEN_OFF | YES |
| denial_reason_code | TEXT | | | ANSI X12 CAS code: CO-4, CO-45, PR-1, etc. | YES |
| era_claim_id | INTEGER | | era_claim_lines.id | FK to matched ERA claim line (NULL if unmatched) | YES |
| appeal_deadline | DATE | | | Computed: service_date + payer filing limit | YES |
| import_source | TEXT | | | EXCEL_IMPORT, 835_PARSE, MANUAL, CSV_UPLOAD | NO |
| created_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | | Record creation timestamp | NO |
| updated_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | | Last modification timestamp (trigger ON UPDATE) | NO |

### Table: era_payments
| Column | Type | Constraints | References | Description | Indexed |
|--------|------|-----------|-----------|-------------|---------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | | Internal row ID | YES |
| filename | TEXT | NOT NULL | | Source 835 filename | YES |
| check_eft_number | TEXT | | | Check or EFT trace number from BPR/TRN | YES |
| payment_amount | DECIMAL(10,2) | | | Total payment amount from BPR segment | NO |
| payment_date | DATE | | | Payment date from BPR segment | NO |
| payment_method | TEXT | | | CHK, ACH, FWT from BPR01 | NO |
| payer_name | TEXT | | | Payer name from N1*PR segment | YES |
| parsed_at | DATETIME | DEFAULT CURRENT_TIMESTAMP | | When this 835 was parsed | NO |

### Table: era_claim_lines
| Column | Type | Constraints | References | Description | Indexed |
|--------|------|-----------|-----------|-------------|---------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | | Internal row ID | YES |
| era_payment_id | INTEGER | FK NOT NULL | era_payments.id | Parent payment | YES |
| claim_id | TEXT | | | CLP01 claim ID (payer's claim number) | YES |
| claim_status | TEXT | | | CLP02: 1=processed primary, 2=processed secondary, 4=denied, 22=reversal | NO |
| billed_amount | DECIMAL(10,2) | | | CLP03 total charge amount | NO |
| paid_amount | DECIMAL(10,2) | | | CLP04 payment amount | NO |
| patient_name_835 | TEXT | | | Patient name from CLP NM1 segment (for matching) | YES |
| service_date_835 | DATE | | | Service date from DTM segment | YES |
| cpt_code | TEXT | | | CPT/HCPCS from SVC01 (e.g., 74177, 78816) | YES |
| cas_group_code | TEXT | | | CAS group: CO (contractual), PR (patient resp), OA (other), PI (payor) | YES |
| cas_reason_code | TEXT | | | CAS reason: 4=not covered, 45=excess charges, 1=deductible, 2=coinsurance, 16=missing info | YES |
| cas_adjustment_amount | DECIMAL(10,2) | | | Dollar amount of adjustment | NO |
| match_confidence | DECIMAL(3,2) | | | 0.00-1.00 confidence score for auto-match to billing_records | NO |
| matched_billing_id | INTEGER | | billing_records.id | FK to matched billing record (NULL if unmatched) | YES |

### Table: denial_reason_codes (Reference Table)
| Column | Type | Constraints | References | Description | Indexed |
|--------|------|-----------|-----------|-------------|---------|
| group_code | TEXT | PK component | | CAS group: CO, PR, OA, PI | YES |
| reason_code | TEXT | PK component | | ANSI X12 reason code number | YES |
| description | TEXT | NOT NULL | | Human-readable description | NO |
| category | TEXT | | | Operational category: AUTH_ISSUE, FRONT_DESK, CODING, PATIENT_RESP, CONTRACT | NO |

Seed with: CO-4 (Not covered/auth required), CO-16 (Missing info/front-desk), CO-45 (Excess charges), PR-1 (Deductible), PR-2 (Coinsurance), PR-3 (Copay), OA-23 (Impact of prior payer adjudication).

### Table: payers
| Column | Type | Constraints | References | Description | Indexed |
|--------|------|-----------|-----------|-------------|---------|
| code | TEXT | PRIMARY KEY | | Payer code: M/M, CALOPTIMA, etc. | YES |
| display_name | TEXT | | | Full name: Medicare/Medicaid, CalOptima, etc. | NO |
| filing_deadline_days | INTEGER | NOT NULL | | Days from service_date to file. M/M=365, CALOPTIMA=180, INS=180, W/C=180 | NO |
| expected_has_secondary | BOOLEAN | DEFAULT FALSE | | TRUE if this payer typically has a secondary (M/M, CALOPTIMA) | NO |
| alert_threshold_pct | DECIMAL(3,2) | DEFAULT 0.25 | | Revenue drop % that triggers alert (0.25 = 25%) | NO |

### Table: fee_schedule
| Column | Type | Constraints | References | Description | Indexed |
|--------|------|-----------|-----------|-------------|---------|
| payer_code | TEXT | PK component | payers.code | Payer code | YES |
| modality | TEXT | PK component | | CT, PET, HMRI, BONE, OPEN, DX | YES |
| expected_rate | DECIMAL(10,2) | NOT NULL | | Expected payment. Global defaults: CT=$395, HMRI=$750, PET=$2500, BONE=$1800, OPEN=$750, DX=$250 | NO |
| underpayment_threshold | DECIMAL(3,2) | DEFAULT 0.80 | | Flag if payment < this % of expected (0.80 = 80%) | NO |

### Table: physicians
| Column | Type | Constraints | References | Description | Indexed |
|--------|------|-----------|-----------|-------------|---------|
| name | TEXT | PRIMARY KEY | | LAST, FIRST. Canonical physician name. | YES |
| physician_type | TEXT | | | REFERRING, READING, BOTH | NO |
| specialty | TEXT | | | Optional: Oncology, Internal Medicine, etc. | NO |
| clinic_affiliation | TEXT | | | Optional: practice or clinic name | NO |
| volume_alert_threshold | DECIMAL(3,2) | DEFAULT 0.30 | | Alert if volume drops >30% vs 3-month avg | NO |

### Table: physician_statements
| Column | Type | Constraints | References | Description | Indexed |
|--------|------|-----------|-----------|-------------|---------|
| id | INTEGER | PRIMARY KEY AUTOINCREMENT | | Statement ID | YES |
| physician_name | TEXT | NOT NULL | physicians.name | Which physician this statement is for | YES |
| statement_period | TEXT | | | YYYY-MM format (e.g., 2025-01) | YES |
| total_owed | DECIMAL(10,2) | | | Total $ owed to physician for this period | NO |
| total_paid | DECIMAL(10,2) | DEFAULT 0 | | Amount paid to physician | NO |
| status | TEXT | DEFAULT 'DRAFT' | | DRAFT, SENT, PAID, PARTIAL, DISPUTED | YES |

---

## FEATURES & BUILD TICKETS

Each row = 1 GitHub Issue. Use feature_id as issue label.

| Feature ID | Title | Category | Sprint | Priority | Depends On | DB Tables | API Routes | Acceptance Criteria | Tech Notes | Est. Hours | Files to Create |
|------------|-------|----------|--------|----------|-----------|-----------|-----------|-------------------|-----------|-----------|------------------|
| F-00 | Project Scaffolding + DB Init | INFRA | Sprint 1 | P0-BLOCKER | none | ALL | /health | flask run starts; SQLite DB created with all tables; /health returns 200; seed data for payers + fee_schedule loaded | Use Flask app factory pattern. Blueprints for each module. Config from .env file. alembic for migrations. | 8 | app/__init__.py, app/models.py, app/config.py, migrations/, seed_data.py, requirements.txt, README.md |
| F-01 | Excel Import Engine | INFRA | Sprint 1 | P0-BLOCKER | F-00 | billing_records | POST /api/import/excel, GET /api/import/status | Upload OCMRI.xlsx → parse Current sheet → insert all 19,936 rows into billing_records. Deduplicate on patient_name+service_date+scan_type+modality. Log import count and errors. | Use openpyxl. Map columns per DATA_SCHEMA table above. Convert Excel serial dates. Handle blank cells as NULL/0. Batch insert 500 rows at a time. | 16 | app/import_engine/excel_importer.py, app/import_engine/__init__.py |
| F-02 | 835 ERA Parser | CORE | Sprint 1 | P0-BLOCKER | F-00 | era_payments, era_claim_lines | POST /api/import/835, GET /api/era/payments, GET /api/era/claims/<id> | Parse X12 835 file → extract ISA/GS/ST envelope, BPR payment, TRN trace, CLP claims, SVC service lines, CAS adjustments. Store all segments relationally. Support batch folder scan. | Custom parser: split on ~ delimiter, parse segment IDs. BPR[01]=payment method, BPR[02]=amount, BPR[16]=date. TRN[02]=check#. CLP[01]=claim_id, CLP[02]=status, CLP[03]=billed, CLP[04]=paid. SVC[01]=CPT, CAS[01]=group, CAS[02]=reason, CAS[03]=amount. Handle multi-SVC and multi-CAS per CLP. | 24 | app/parser/era_835_parser.py, app/parser/__init__.py, tests/test_835_parser.py |
| F-03 | Auto-Match Engine (835 → Billing) | CORE | Sprint 2 | P1-HIGH | F-01, F-02 | billing_records, era_claim_lines | POST /api/match/run, GET /api/match/results, POST /api/match/confirm/<id> | Match era_claim_lines to billing_records using: normalize(patient_name) fuzzy match (>85%), service_date ±2 days, modality match. Assign confidence 0.0-1.0. Auto-accept >0.95. Queue 0.80-0.95 for review. Reject <0.80. | Use rapidfuzz for name matching. Normalize: strip(), upper(), remove middle initials, handle LAST FIRST vs FIRST LAST. Composite score = 0.5*name + 0.3*date + 0.2*modality. | 20 | app/matching/match_engine.py, app/matching/__init__.py, templates/match_review.html |
| F-04 | Denial Tracking & Appeal Queue | REVENUE | Sprint 2 | P1-HIGH | F-02, F-03 | billing_records | GET /api/denials, GET /api/denials/queue, POST /api/denials/<id>/appeal, POST /api/denials/<id>/resolve | Identify all claims where total_payment=0 OR era CLP02=4 (denied). Queue sorted by: amount DESC, age ASC. Track status: DENIED→APPEALED→RESOLVED/WRITTEN_OFF. Show denial reason codes from CAS. 722 known $0 claims to process. | Default queue sort: recoverability_score = billed_amount * (1 - days_old/365). Filter by carrier, modality, date range. Bulk actions for batch appeals. | 16 | app/revenue/denial_tracker.py, templates/denial_queue.html, templates/denial_detail.html |
| F-05 | Underpayment Detector | REVENUE | Sprint 1 | P1-HIGH | F-01 | billing_records, fee_schedule | GET /api/underpayments, GET /api/underpayments/summary | Compare total_payment vs fee_schedule.expected_rate for each paid claim. Flag if payment < underpayment_threshold (default 80%). Group by carrier + modality. Current finding: 55.8% of paid claims underpaid, $913K gap. | JOIN billing_records ON modality = fee_schedule.modality AND insurance_carrier = fee_schedule.payer_code. Calculate variance = total_payment - expected_rate. Summary: count flagged, total variance, worst carrier, worst modality. | 12 | app/revenue/underpayment_detector.py, templates/underpayments.html |
| F-06 | Timely Filing Deadline Tracker | REVENUE | Sprint 1 | P1-HIGH | F-01 | billing_records, payers | GET /api/filing-deadlines, GET /api/filing-deadlines/alerts | Compute appeal_deadline = service_date + payers.filing_deadline_days. Flag claims where: total_payment=0 AND today > (appeal_deadline - 30 days). Categories: PAST_DEADLINE, WARNING_30DAY, SAFE. Current finding: 36 past-deadline, 8 in warning. | Payer deadlines: M/M=365, CALOPTIMA=180, INS=180, W/C=180, FAMILY=180, ONE CALL=90, OC ADV=180. Update appeal_deadline on billing_records during import. | 8 | app/revenue/filing_deadlines.py, templates/filing_deadlines.html |
| F-07 | Secondary Insurance Follow-Up | REVENUE | Sprint 2 | P1-HIGH | F-01 | billing_records, payers | GET /api/secondary-followup, POST /api/secondary-followup/<id>/mark | Identify claims where primary_payment > 0 AND secondary_payment = 0 AND payers.expected_has_secondary = TRUE. Queue for billing follow-up. Current finding: 1,919 claims, est. $643K missing. | Carriers with expected secondary: M/M (Medi-Cal crossover), CALOPTIMA. Flag M/M claims without secondary as highest priority. | 10 | app/revenue/secondary_followup.py, templates/secondary_queue.html |
| F-08 | Duplicate Claim Detector | REVENUE | Sprint 2 | P2-MEDIUM | F-01 | billing_records | GET /api/duplicates, POST /api/duplicates/<id>/legitimate | Hash patient_name+service_date+scan_type+modality. Flag exact matches. Exception: C.A.P description legitimately generates CHEST+ABDOMEN+PELVIS on same date—do NOT flag these. Allow marking as legitimate. | GROUP BY patient_name, service_date, scan_type, modality HAVING COUNT(*) > 1. Filter OUT records where description='C.A.P' or 'CAP'. Side-by-side comparison view. | 8 | app/revenue/duplicate_detector.py, templates/duplicates.html |
| F-09 | Payer Contract Monitor & Alerts | ANALYTICS | Sprint 3 | P1-HIGH | F-01 | billing_records, payers | GET /api/payer-alerts, GET /api/payer-monitor, GET /api/payer-monitor/<carrier> | Monthly compare: if carrier revenue OR volume drops >alert_threshold_pct vs prior 3-month avg, generate alert. Known issues: ONE CALL $123K→$0, W/C dropped 63%, SELF PAY dropped 88%. Dashboard with YoY trends per carrier. | SQL: SELECT insurance_carrier, strftime('%Y-%m', service_date) as month, SUM(total_payment), COUNT(*) GROUP BY 1,2. Compare current month vs AVG of prior 3. Color code: RED >50% drop, YELLOW >25%, GREEN stable. | 12 | app/analytics/payer_monitor.py, templates/payer_dashboard.html, templates/payer_detail.html |
| F-10 | Physician Statement Reconciliation | REVENUE | Sprint 4 | P2-MEDIUM | F-01 | billing_records, physician_statements, physicians | GET /api/statements, POST /api/statements/generate, GET /api/statements/<id>/pdf | Auto-generate monthly statements for reading physicians (Jhangiani=$30,880 owed, Beach Clinical=$5,000, Vu Phan=TBD). Match billing_records WHERE reading_physician or insurance_carrier = physician name. Track OWED vs PAID. | Use ReportLab or WeasyPrint for PDF. Template: header with physician name + period, line items (patient, date, scan, amount), totals. Export to C:\OCDR\export\statements\ | 16 | app/revenue/physician_statements.py, templates/statements.html, templates/statement_pdf.html |
| F-11 | Folder Monitor + Auto-Ingest | INFRA | Sprint 3 | P1-HIGH | F-01, F-02 | billing_records, era_payments | POST /api/monitor/start, POST /api/monitor/stop, GET /api/monitor/status | Watch C:\OCDR\import\ for new files. Route by extension: .835/.edi → ERA parser, .csv → CSV importer, .pdf → PDF parser, .xlsx → Excel importer. Move processed to /processed/, failed to /errors/. Log all. | Use watchdog library. Separate thread. File type detection by extension + magic bytes. Queue files for processing. Configurable poll interval (default 30s). | 16 | app/monitor/folder_watcher.py, app/monitor/__init__.py |
| F-12 | CSV/PDF Import Parsers | INFRA | Sprint 3 | P2-MEDIUM | F-11 | billing_records | POST /api/import/csv, POST /api/import/pdf | CSV: auto-detect column mapping from headers (fuzzy match to DATA_SCHEMA). PDF: extract tables from digital PDFs using pdfplumber. OCR for scanned docs using Tesseract. | CSV: pandas read_csv with header matching. PDF: pdfplumber.extract_tables(). OCR: pytesseract.image_to_string() with OpenCV preprocessing (grayscale, threshold, deskew). Side-by-side review UI for OCR output. | 20 | app/import_engine/csv_importer.py, app/import_engine/pdf_importer.py, app/import_engine/ocr_engine.py |
| F-13 | PSMA PET Tracking | ANALYTICS | Sprint 4 | P2-MEDIUM | F-01 | billing_records | GET /api/psma, GET /api/psma/summary | Flag billing_records WHERE description LIKE '%PSMA%' OR modality='PET' AND description LIKE '%PSMA%'. Separate dashboard: volume, revenue, avg reimbursement ($8,046/scan vs $2,320 standard PET). YoY trend. 2025: 52 PSMA scans = $418K. | Set is_psma=TRUE during import if description contains 'PSMA'. Chart: PSMA vs Standard PET side-by-side bar chart by year. | 6 | app/analytics/psma_tracker.py, templates/psma_dashboard.html |
| F-14 | Gado Contrast Cost Tracking | ANALYTICS | Sprint 5 | P2-MEDIUM | F-01 | billing_records | GET /api/gado, GET /api/gado/margin | Dashboard: total gado claims (1,916), revenue ($838K), by physician, by year. Cost analysis: configurable $/dose (default $50). Margin calc: revenue per $1 gado cost ($8.75). 99% of gado is HMRI. | Filter billing_records WHERE gado_used=TRUE. Group by referring_doctor, service_year. Config: gado_cost_per_dose in app config table. | 6 | app/analytics/gado_tracker.py, templates/gado_dashboard.html |
| F-15 | Referring Physician Analytics | ANALYTICS | Sprint 5 | P2-MEDIUM | F-01 | billing_records, physicians | GET /api/physicians, GET /api/physicians/<name>, GET /api/physicians/alerts | Top 30+ physicians ranked by revenue. Per-physician drilldown: revenue by modality, by year, gado usage, insurance mix. Alert if volume drops >30% vs 3-month avg. Top 10 = 54.9% of total revenue. | GROUP BY referring_doctor with SUMs and COUNTs. Subqueries for modality and year breakdowns. Volume trend: compare current month count vs AVG(prior 3 months). | 10 | app/analytics/physician_analytics.py, templates/physician_dashboard.html, templates/physician_detail.html |
| F-16 | Denial Reason Code Analytics | ANALYTICS | Sprint 4 | P2-MEDIUM | F-02, F-03 | era_claim_lines | GET /api/denial-analytics, GET /api/denial-analytics/pareto | Aggregate CAS reason codes: top 10 by frequency, top 10 by $ amount, by carrier, by modality. Pareto chart (80/20). Trend over time. If CO-16 is top = front-desk issue; CO-4 = auth issue. | ANSI X12 reason code reference: CO-4=not covered, CO-16=missing info, CO-45=excess charges, PR-1=deductible, PR-2=coinsurance, PR-3=copay. Store reference table. Use Chart.js horizontal bar + line combo. | 10 | app/analytics/denial_analytics.py, templates/denial_analytics.html |
| F-17 | Check/EFT Payment Matching | CORE | Sprint 4 | P2-MEDIUM | F-02 | era_payments, era_claim_lines | GET /api/payments, GET /api/payments/<check_number>, POST /api/payments/reconcile | Group era_claim_lines by parent era_payment (check/EFT). Show all claims under each check. Import bank statement CSV to match deposits to checks. Flag unmatched deposits and unmatched checks. | Bank CSV import: date, amount, description (contains check#). Match era_payments.payment_amount to bank deposit amount ±$0.01. Match era_payments.check_eft_number to bank description. | 12 | app/core/payment_matching.py, templates/payment_reconciliation.html |
| F-18 | Excel CSV Export Bridge | INFRA | Sprint 5 | P2-MEDIUM | F-01 | billing_records | GET /api/export/csv, POST /api/export/trigger | Export billing_records to C:\OCDR\export\master_data.csv every 15 min (configurable). Match Current sheet column order exactly (22 cols). Excel Power Query connects to this CSV. | CSV must match Excel col order: Patient,Doctor,Scan,Gado,Insurance,Type,Date,Primary,Secondary,Total,Extra,ReadBy,ID,Birth Date,Patient Name,S Date,Modalities,Description,Month,Year,New. Date as Excel serial number. | 6 | app/export/csv_exporter.py |
| F-19 | Local Dashboard Web UI | UI | Sprint 6 | P3-LOW | F-05,F-06,F-07,F-09,F-15 | ALL | GET / (dashboard home) | Single-page dashboard at localhost:5000. KPI cards: Total Revenue, Unpaid Claims, Underpayments, Filing Deadline Alerts, Secondary Follow-Up Queue. Charts: Revenue by carrier (bar), Monthly trend (line), Denials by reason (pie). Click any KPI to drill into detail page. | Bootstrap 5 grid. Chart.js for all charts. Jinja2 template inheriting from base.html. API-driven: each card calls /api/* endpoint. Auto-refresh every 60s via JS fetch(). | 16 | app/ui/dashboard.py, templates/base.html, templates/dashboard.html, static/css/style.css, static/js/dashboard.js |
| F-20 | Local Backup & Version History | INFRA | Sprint 1 | P1-HIGH | F-00 | n/a | POST /api/backup/run, GET /api/backup/status, GET /api/backup/history | Backup ocdr.db + Excel workbook to C:\OCDR\backup\. Retention: 7 daily, 4 weekly, 12 monthly. SHA256 integrity check on each backup. Robocopy to NAS if configured. Windows Task Scheduler integration. | shutil.copy2() for DB backup. SHA256 hashlib. Schedule via schtasks.exe /create command. Backup naming: ocdr_YYYYMMDD_HHMMSS.db. Prune old backups with retention policy. | 8 | app/infra/backup_manager.py, scripts/install_backup_schedule.bat |

---

## API ROUTES – Flask Endpoints

| Method | Route | Feature | Request | Response | Description |
|--------|-------|---------|---------|----------|-------------|
| GET | /health | F-00 | none | JSON {status, db_size, record_count, uptime} | Health check |
| GET | / | F-19 | none | HTML dashboard | Main dashboard |
| POST | /api/import/excel | F-01 | multipart/form-data (file) | JSON {imported, skipped, errors, duration_ms} | Import OCMRI.xlsx |
| GET | /api/import/status | F-01 | none | JSON {last_import, total_records, source} | Import status |
| POST | /api/import/835 | F-02 | multipart/form-data OR {folder_path} | JSON {files_parsed, claims_found, payments_total} | Parse 835 file(s) |
| POST | /api/import/csv | F-12 | multipart/form-data (file) | JSON {imported, skipped, errors, column_mapping} | Import CSV file |
| POST | /api/import/pdf | F-12 | multipart/form-data (file) | JSON {imported, skipped, errors, ocr_used} | Import PDF file |
| GET | /api/era/payments | F-02 | ?page=&per_page=&payer=&date_from=&date_to= | JSON paginated list | List ERA payments |
| GET | /api/era/claims/<id> | F-02 | none | JSON claim detail | Single claim detail |
| POST | /api/match/run | F-03 | {confidence_threshold: 0.85} | JSON {matched, review_needed, unmatched, duration_ms} | Run auto-match |
| GET | /api/match/results | F-03 | ?status=review&page= | JSON paginated results | Match results queue |
| POST | /api/match/confirm/<id> | F-03 | {action: accept\|reject} | JSON {updated: true} | Confirm/reject match |
| GET | /api/denials | F-04 | ?status=&carrier=&modality=&sort_by= | JSON paginated list | All denials |
| GET | /api/denials/queue | F-04 | ?limit=50 | JSON sorted by score | Priority appeal queue |
| POST | /api/denials/<id>/appeal | F-04 | {notes, appeal_date} | JSON {status: APPEALED} | Mark as appealed |
| POST | /api/denials/<id>/resolve | F-04 | {resolution: PAID\|WRITTEN_OFF, amount} | JSON {status: RESOLVED} | Resolve denial |
| GET | /api/underpayments | F-05 | ?carrier=&modality=&threshold= | JSON paginated list | Underpaid claims |
| GET | /api/underpayments/summary | F-05 | none | JSON {total_flagged, total_variance, by_carrier[], by_modality[]} | Summary stats |
| GET | /api/filing-deadlines | F-06 | ?status=PAST\|WARNING\|SAFE | JSON paginated list | Filing deadline status |
| GET | /api/filing-deadlines/alerts | F-06 | none | JSON {past_deadline, warning, details[]} | Active alerts only |
| GET | /api/secondary-followup | F-07 | ?carrier=&page= | JSON paginated queue | Missing secondary queue |
| POST | /api/secondary-followup/<id>/mark | F-07 | {status: billed\|resolved\|waived} | JSON {updated: true} | Mark secondary follow-up action |
| GET | /api/duplicates | F-08 | ?include_legitimate=false | JSON grouped pairs | Duplicate claims |
| POST | /api/duplicates/<id>/legitimate | F-08 | {reason} | JSON {marked: true} | Mark duplicate as legitimate |
| GET | /api/payer-alerts | F-09 | none | JSON {alerts: [...]} | Active payer alerts |
| GET | /api/payer-monitor | F-09 | ?year= | JSON {carriers[], monthly_data[]} | All carriers overview |
| GET | /api/payer-monitor/<carrier> | F-09 | ?year= | JSON {monthly_data[], yoy_comparison} | Carrier detail |
| GET | /api/physicians | F-15 | ?sort_by=revenue&limit=30 | JSON ranked list | Physician rankings |
| GET | /api/physicians/<name> | F-15 | none | JSON {revenue, claims, by_modality, ...} | Physician detail |
| GET | /api/physicians/alerts | F-15 | none | JSON {alerts: [...]} | Physician volume drop alerts |
| GET | /api/psma | F-13 | ?year= | JSON {psma_count, psma_revenue, ...} | PSMA dashboard data |
| GET | /api/psma/summary | F-13 | none | JSON {total_scans, total_revenue, avg_reimbursement, yoy_trend[]} | PSMA summary |
| GET | /api/gado | F-14 | none | JSON {total_claims, total_revenue, ...} | Gado analytics |
| GET | /api/gado/margin | F-14 | none | JSON {cost_per_dose, total_cost, total_revenue, margin_pct, by_physician[]} | Gado margin analysis |
| GET | /api/statements | F-10 | ?physician=&period=&status= | JSON paginated list | List all statements |
| POST | /api/statements/generate | F-10 | {physician, period: YYYY-MM} | JSON {statement_id, total_owed, ...} | Generate statement |
| GET | /api/statements/<id>/pdf | F-10 | none | application/pdf | Download statement PDF |
| POST | /api/monitor/start | F-11 | {folder_path} | JSON {monitoring: true} | Start folder watch |
| POST | /api/monitor/stop | F-11 | none | JSON {monitoring: false} | Stop folder watch |
| GET | /api/monitor/status | F-11 | none | JSON {running, folder_path, files_processed, last_activity} | Monitor status |
| GET | /api/export/csv | F-18 | none | text/csv attachment | Download current CSV export |
| POST | /api/export/trigger | F-18 | none | JSON {rows_exported, path, timestamp} | Force CSV export |
| POST | /api/backup/run | F-20 | none | JSON {backup_path, size_bytes, sha256} | Run backup now |
| GET | /api/backup/status | F-20 | none | JSON {last_backup, next_scheduled, db_size_bytes} | Backup status |
| GET | /api/backup/history | F-20 | ?limit=20 | JSON [{backup_path, timestamp, size_bytes, sha256}] | Backup history |
| GET | /api/denial-analytics | F-16 | ?carrier=&top_n=10 | JSON {by_reason[], by_carrier[], by_modality[]} | Denial analytics |
| GET | /api/denial-analytics/pareto | F-16 | ?carrier= | JSON {reason_codes[], cumulative_pct[], pareto_cutoff} | Pareto (80/20) chart data |
| GET | /api/payments | F-17 | ?check_number=&date_from= | JSON paginated list | Check/EFT listing |
| POST | /api/payments/reconcile | F-17 | multipart/form-data (bank CSV) | JSON {matched, unmatched_deposits, unmatched_checks} | Bank reconciliation |

---

## FILE STRUCTURE – GitHub Repo Layout

```
ocdr/
├── app/
│   ├── __init__.py                    (F-00: App factory)
│   ├── models.py                      (F-00: SQLAlchemy models)
│   ├── config.py                      (F-00: Configuration)
│   ├── import_engine/
│   │   ├── __init__.py                (F-01: Blueprint)
│   │   ├── excel_importer.py          (F-01: OCMRI.xlsx parser)
│   │   ├── csv_importer.py            (F-12: Generic CSV)
│   │   ├── pdf_importer.py            (F-12: PDF extraction)
│   │   └── ocr_engine.py              (F-12: Tesseract OCR)
│   ├── parser/
│   │   ├── __init__.py                (F-02: Blueprint)
│   │   └── era_835_parser.py          (F-02: X12 835 parser)
│   ├── matching/
│   │   ├── __init__.py                (F-03: Blueprint)
│   │   └── match_engine.py            (F-03: Fuzzy matching)
│   ├── revenue/
│   │   ├── __init__.py                (Blueprint registration)
│   │   ├── denial_tracker.py          (F-04: Denial queue)
│   │   ├── underpayment_detector.py   (F-05: Fee comparison)
│   │   ├── filing_deadlines.py        (F-06: Timely filing)
│   │   ├── secondary_followup.py      (F-07: Secondary billing)
│   │   ├── duplicate_detector.py      (F-08: Duplicate detection)
│   │   └── physician_statements.py    (F-10: Physician reports)
│   ├── analytics/
│   │   ├── __init__.py                (Blueprint registration)
│   │   ├── payer_monitor.py           (F-09: Payer alerts)
│   │   ├── physician_analytics.py     (F-15: Physician revenue)
│   │   ├── psma_tracker.py            (F-13: PSMA tracking)
│   │   ├── gado_tracker.py            (F-14: Gado analytics)
│   │   └── denial_analytics.py        (F-16: Denial reasons)
│   ├── core/
│   │   ├── __init__.py                (Blueprint registration)
│   │   └── payment_matching.py        (F-17: Check matching)
│   ├── monitor/
│   │   ├── __init__.py                (F-11: Blueprint)
│   │   └── folder_watcher.py          (F-11: Watchdog monitor)
│   ├── export/
│   │   ├── __init__.py                (Blueprint registration)
│   │   └── csv_exporter.py            (F-18: CSV export)
│   ├── infra/
│   │   ├── __init__.py                (Blueprint registration)
│   │   └── backup_manager.py          (F-20: Backup + retention)
│   └── ui/
│       └── dashboard.py               (F-19: Dashboard routes)
├── templates/
│   ├── base.html                      (F-19: Base template)
│   ├── dashboard.html                 (F-19: Main dashboard)
│   ├── match_review.html              (F-03: Match queue)
│   ├── denial_queue.html              (F-04: Denial queue)
│   ├── denial_detail.html             (F-04: Denial detail)
│   ├── underpayments.html             (F-05: Underpayment report)
│   ├── filing_deadlines.html          (F-06: Filing alerts)
│   ├── secondary_queue.html           (F-07: Secondary follow-up)
│   ├── duplicates.html                (F-08: Duplicate detection)
│   ├── payer_dashboard.html           (F-09: Payer monitor)
│   ├── payer_detail.html              (F-09: Payer detail)
│   ├── statements.html                (F-10: Physician statements)
│   ├── statement_pdf.html             (F-10: Statement PDF)
│   ├── psma_dashboard.html            (F-13: PSMA dashboard)
│   ├── gado_dashboard.html            (F-14: Gado dashboard)
│   ├── physician_dashboard.html       (F-15: Physician rankings)
│   ├── physician_detail.html          (F-15: Physician detail)
│   ├── denial_analytics.html          (F-16: Denial reason analytics)
│   └── payment_reconciliation.html    (F-17: Check/EFT reconciliation)
├── static/
│   ├── css/
│   │   └── style.css                  (F-19: Bootstrap 5 + custom)
│   └── js/
│       └── dashboard.js               (F-19: Auto-refresh + charts)
├── tests/
│   ├── __init__.py
│   ├── conftest.py                    (Shared fixtures: test DB, sample data, Flask test client)
│   ├── test_835_parser.py             (F-02: Parser tests)
│   ├── test_excel_importer.py         (F-01: Import tests)
│   ├── test_match_engine.py           (F-03: Fuzzy matching tests)
│   ├── test_business_rules.py         (BR-01 through BR-11 validation)
│   └── test_api_routes.py             (API endpoint integration tests)
├── migrations/                        (F-00: Alembic migrations)
├── scripts/
│   ├── install_service.bat            (Windows Service installer)
│   └── install_backup_schedule.bat    (Task Scheduler setup)
├── seed_data.py                       (F-00: Seed payers + fee schedule)
├── requirements.txt                   (F-00: Dependencies)
├── .env.example                       (F-00: Config template)
└── README.md                          (F-00: Setup + architecture)
```

---

## SPRINT PLAN – Build Order with Dependencies

| Sprint | Timeframe | Features | Deliverables | Depends On | Revenue Impact |
|--------|-----------|----------|--------------|-----------|----------------|
| **Sprint 1** | Weeks 1-2 | F-00, F-01, F-02, F-05, F-06, F-20 | Working app scaffold. Excel import (19,936 rows). 835 parser reads local files. Underpayment report ($913K gap identified). Filing deadline alerts (36 past-deadline). Daily backup to NAS. | none | Immediate: flag $150K+ underpayments. Prevent future timely filing losses. |
| **Sprint 2** | Weeks 3-4 | F-03, F-04, F-07, F-08 | 835-to-billing auto-match at 85%+ confidence. Denial queue with reason codes (722 claims). Secondary follow-up queue ($643K missing). Duplicate detector. | Sprint 1 | Work 628 unpaid claims under 120 days. Identify $643K in missing secondary payments. |
| **Sprint 3** | Weeks 5-6 | F-09, F-11, F-12 | Payer contract alerts (One Call $123K→$0 flagged). Folder monitor auto-ingests new 835/CSV/PDF. CSV + PDF + OCR import support. | Sprint 1-2 | Save 10-20 hrs/month manual entry. Catch payer contract issues within 30 days. |
| **Sprint 4** | Weeks 7-8 | F-10, F-13, F-16, F-17 | Auto physician statements (Jhangiani $30,880 owed, Beach $5,000). PSMA tracking ($418K/yr). Denial reason analytics (Pareto). Bank reconciliation. | Sprint 2-3 | Save 5-8 hrs/month reports. Accurate physician payables. PSMA profitability visibility. |
| **Sprint 5** | Weeks 9-10 | F-14, F-15, F-18 | Gado contrast margin analysis ($838K revenue, 88.6% margin). Referring physician dashboard (top 30, 54.9% of revenue). CSV export bridge to Excel. | Sprint 1 | Excel auto-refreshes. Gado negotiation data. Referrer relationship management. |
| **Sprint 6** | Weeks 11-12 | F-19 | Interactive local dashboard at localhost:5000. All KPIs on one screen. Drill-down into any metric. Chart.js visualizations. | Sprint 1-5 | Full system operational. At-a-glance visibility without opening Excel. |

---

## SEED DATA – Payer Configuration

| Code | Display Name | Filing Deadline (days) | Expected Secondary | Alert Threshold | Notes |
|------|-------------|----------------------|-------------------|-----------------|-------|
| M/M | Medicare/Medicaid | 365 | TRUE | 0.25 | Largest payer: $4.46M, 7,559 claims. Often has Medi-Cal secondary. |
| CALOPTIMA | CalOptima Managed Medicaid | 180 | TRUE | 0.25 | $2.21M, 2,381 claims. May have secondary. |
| FAMILY | Family Health Plan | 180 | FALSE | 0.25 | $1.39M, 1,881 claims. |
| INS | Commercial Insurance (General) | 180 | FALSE | 0.25 | $1.16M, 2,327 claims. Revenue declining YoY. |
| VU PHAN | Vu Phan Physician Group | 180 | FALSE | 0.25 | $641K, 1,383 claims. Internal physician billing. |
| W/C | Workers Compensation | 180 | FALSE | 0.25 | $498K, 1,544 claims. 2025 pace declining sharply. |
| BEACH | Beach Clinical Labs | 180 | FALSE | 0.25 | $180K, 352 claims. Internal billing. Owes $5,000. |
| ONE CALL | One Call Care Management | 90 | FALSE | 0.5 | $179K, 712 claims. CRITICAL: $0 since 2025. Likely contract terminated. |
| OC ADV | One Call Advanced | 180 | FALSE | 0.25 | $153K, 169 claims. Related to One Call. Also declining. |
| SELF PAY | Self Pay / Uninsured | 9999 | FALSE | 0.25 | Volume declining 88%. Check pricing competitiveness. |
| SELFPAY | Self Pay (alternate code) | 9999 | FALSE | 0.25 | Duplicate code for SELF PAY. Normalize to SELF PAY on import. |
| STATE | State Programs | 365 | FALSE | 0.25 | Small volume. |
| COMP | Complimentary / Charity | 9999 | FALSE | 0.5 | Typically $0 or near-$0 payments. |
| X | Unknown / Unclassified | 180 | FALSE | 0.5 | Investigate these records. May need reclassification. |
| JHANGIANI | Jhangiani Physician Group | 180 | FALSE | 0.25 | Internal physician billing. Owes $30,880. Has custom HMRI rate ($950 with gado). |
| GH | Group Health | 180 | FALSE | 0.25 | Minimal volume. Single record seen. |

---

## SEED DATA – Fee Schedule (Default Rates)

| Modality | Expected Rate | Underpayment Threshold | Payer Code | Notes |
|----------|---------------|----------------------|-----------|-------|
| CT | $395 | 0.80 | DEFAULT | Global default. Override per payer as needed. |
| HMRI | $750 | 0.80 | DEFAULT | With gado add $200 premium. 89% of HMRI claims are underpaid. |
| PET | $2,500 | 0.80 | DEFAULT | Standard PET/CT. PET actually overpaid on average ($2,683 avg). |
| BONE | $1,800 | 0.80 | DEFAULT | Bone scan / nuclear medicine. |
| OPEN | $750 | 0.80 | DEFAULT | Open MRI. Same rate as HMRI. |
| DX | $250 | 0.80 | DEFAULT | Diagnostic X-ray. Lowest rate modality. |
| HMRI | $950 | 0.80 | JHANGIANI | Jhangiani pays $950 for HMRI with gado, $750 without. |
| PET | $8,046 | 0.80 | DEFAULT (PSMA) | PSMA PET avg reimbursement: $8,046/scan. 3.47x standard PET. |

---

## BUSINESS RULES

| Rule ID | Rule Name | Logic | Action | Priority |
|---------|-----------|-------|--------|----------|
| BR-01 | C.A.P Exception | IF description = 'C.A.P' AND scan_type IN ('CHEST','ABDOMEN','PELVIS') AND same patient+date has 3 records THEN NOT a duplicate | Exclude from duplicate detection. Mark as cap_exception=TRUE. | CRITICAL |
| BR-02 | PSMA Detection | IF description LIKE '%PSMA%' OR (modality='PET' AND description LIKE '%Ga-68%' OR '%gallium%') THEN is_psma=TRUE | Set is_psma flag. Use PSMA fee schedule ($8,046) not standard PET ($2,500). | HIGH |
| BR-03 | Gado Premium | IF gado_used=TRUE AND modality IN ('HMRI','OPEN') THEN expected_rate += $200 | Add $200 gado premium to expected rate for underpayment comparison. | MEDIUM |
| BR-04 | Secondary Expected | IF insurance_carrier IN ('M/M','CALOPTIMA') AND primary_payment > 0 AND secondary_payment = 0 THEN flag for secondary follow-up | Add to secondary follow-up queue. Priority = M/M first (Medi-Cal crossover). | HIGH |
| BR-05 | Timely Filing Alert | IF total_payment = 0 AND TODAY() > (service_date + filing_deadline_days - 30) THEN alert | WARNING if within 30 days. PAST_DEADLINE if expired. Sorted by days_remaining ASC. | CRITICAL |
| BR-06 | Payer Drop Alert | IF current_month_revenue < (avg_prior_3_months * (1 - alert_threshold_pct)) THEN alert | RED if drop >50%. YELLOW if >25%. Check both revenue AND volume. | HIGH |
| BR-07 | Physician Volume Alert | IF current_month_claims < (avg_prior_3_months * (1 - volume_alert_threshold)) THEN alert | Alert on referring physician volume drop. Losing a top referrer = major revenue risk. | MEDIUM |
| BR-08 | Denial Recoverability Score | recoverability_score = billed_amount * max(0, 1 - (days_since_service / filing_deadline_days)). Score is in dollars; higher = more recoverable. Clamps to 0 when past filing deadline. | Sort denial queue by score DESC. Highest-value, most-recent claims first. | HIGH |
| BR-09 | Auto-Match Confidence | score = (0.50 * name_similarity) + (0.30 * date_match) + (0.20 * modality_match). name_similarity via rapidfuzz ratio. date_match: exact=1.0, ±1day=0.8, ±2days=0.5. modality_match: exact=1.0, else 0.0. | Auto-accept if score >= 0.95. Manual review if 0.80-0.95. Reject if < 0.80. | CRITICAL |
| BR-10 | SELFPAY Normalization | IF insurance_carrier IN ('SELFPAY','SELF-PAY','SELF PAY','CASH') THEN normalize to 'SELF PAY' | Normalize on import. Prevents fragmented payer reporting. | MEDIUM |
| BR-11 | Underpayment Detection | IF total_payment > 0 AND total_payment < (expected_rate * underpayment_threshold) THEN flag as underpaid | Add to underpayment report. Calculate variance = total_payment - expected_rate. | HIGH |

---

## HOW TO USE THIS SPEC

1. **Export as needed:** This document is the master spec.
2. **Feed to AI agents:** Use with Claude Opus 4.6, Cursor, Devin, or any AI coding agent.
3. **Create GitHub issues:** Each row in the FEATURES table = 1 GitHub Issue.
4. **Build in sprint order:** Follow SPRINT_PLAN. Each sprint's `depends_on` field indicates blocking features.
5. **Test against acceptance criteria:** Validate each feature before moving to the next.
6. **Update status:** After implementation, add a `status` column (DONE/IN_PROGRESS/BLOCKED) to FEATURES table.
7. **HIPAA compliance:** This spec contains NO PHI. Never commit OCMRI.xlsx to GitHub. Use seed_data.py with synthetic test data.
