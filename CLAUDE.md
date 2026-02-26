# CLAUDE.md — AI Agent Guide for OCDR

## Project Overview

**OCDR** (Billing Reconciliation System) is a healthcare billing analytics and reconciliation platform for medical imaging operations. It imports claims from Excel/CSV/835 EDI files, reconciles payments against expected fee schedules, detects denials and underpayments, and provides analytics dashboards — all running 100% locally with zero cloud dependencies.

**Stack:** Python 3.11+ · Flask 3.x · SQLite 3 · Bootstrap 5.3 · Chart.js 4.x · Jinja2

**Constraint:** 100% LOCAL — zero cloud, zero internet, zero external APIs. HIPAA-compliant PHI handling.

## Repository Structure

```
ocdr/
├── CLAUDE.md                  ← You are here
├── BUILD_SPEC.md              ← Master specification (source of truth)
├── README.md                  ← Setup and usage guide
├── .gitignore
├── requirements.txt           ← Python dependencies (pip)
├── seed_data.py               ← Seed payers + fee schedule into DB
├── .env.example               ← Environment variable template
├── app/
│   ├── __init__.py            ← Flask app factory (create_app)
│   ├── models.py              ← SQLAlchemy models (all 6 tables)
│   ├── config.py              ← Configuration from .env
│   ├── import_engine/         ← Excel, CSV, PDF, OCR importers
│   ├── parser/                ← X12 835 ERA parser
│   ├── matching/              ← Fuzzy matching engine (835→billing)
│   ├── revenue/               ← Denials, underpayments, deadlines, secondary, duplicates, statements
│   ├── analytics/             ← Payer monitor, physician analytics, PSMA, Gado, denial analytics
│   ├── core/                  ← Check/EFT payment matching
│   ├── monitor/               ← Folder watcher (watchdog)
│   ├── export/                ← CSV export bridge
│   ├── infra/                 ← Backup manager
│   └── ui/                    ← Dashboard routes
├── templates/                 ← Jinja2 HTML templates
├── static/css/ static/js/     ← Bootstrap 5 + Chart.js + custom
├── tests/                     ← pytest test suite
├── migrations/                ← Alembic DB migrations
└── scripts/                   ← Windows Service & Task Scheduler installers
```

## Key Commands

```bash
# Setup
python -m venv venv && source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
python seed_data.py

# Run
flask run                      # Development server at localhost:5000

# Test
pytest tests/                  # Run all tests
pytest tests/test_835_parser.py  # Run specific test file

# Database
flask db init                  # Initialize Alembic
flask db migrate -m "message"  # Generate migration
flask db upgrade               # Apply migrations

# Backup
POST /api/backup/run           # Trigger manual backup
```

## Architecture

### Application Factory Pattern
The app uses Flask's app factory (`create_app()` in `app/__init__.py`). Each module registers as a Flask Blueprint.

### Database (SQLite — single file: `ocdr.db`)
8 tables:
| Table | Purpose |
|-------|---------|
| `billing_records` | Master claims table (~19,936 rows from OCMRI.xlsx) |
| `era_payments` | Parsed X12-835 ERA payment headers |
| `era_claim_lines` | Individual claim lines from 835 files |
| `denial_reason_codes` | ANSI X12 CAS reason code reference (CO-4, PR-1, etc.) |
| `payers` | Insurance carrier configuration + filing deadlines |
| `fee_schedule` | Expected rates per payer/modality |
| `physicians` | Referring/reading physician profiles |
| `physician_statements` | Monthly physician payment statements |

### Module Responsibilities
Each `app/` subdirectory is a Flask Blueprint with its own routes:
- **import_engine** — Parse Excel (openpyxl), CSV (pandas), PDF (pdfplumber), OCR (Tesseract+OpenCV)
- **parser** — X12 835 EDI parser (segment delimiter `~`, element delimiter `*`)
- **matching** — Fuzzy match ERA claims → billing records using rapidfuzz (composite score: 50% name + 30% date + 20% modality)
- **revenue** — Denial tracking, underpayment detection, timely filing deadlines, secondary follow-up, duplicate detection, physician statements
- **analytics** — Payer contract monitoring, physician rankings, PSMA PET tracking, Gado contrast analysis, denial reason analytics
- **core** — Check/EFT payment reconciliation with bank statements
- **monitor** — Watchdog-based folder watcher for auto-ingest
- **export** — CSV export bridge for Excel Power Query
- **infra** — Backup with retention policy (7 daily, 4 weekly, 12 monthly)
- **ui** — Main dashboard with KPI cards and Chart.js visualizations

## Coding Conventions

### Naming
- **Models/Classes:** PascalCase — `BillingRecord`, `Era835Parser`, `FuzzyMatchEngine`
- **Functions/methods:** snake_case — `parse_835_file()`, `normalize_patient_name()`
- **Database columns:** snake_case — `patient_name`, `service_date`, `total_payment`
- **API routes:** kebab-case with `/api/` prefix — `/api/filing-deadlines`, `/api/secondary-followup`
- **Templates:** snake_case — `denial_queue.html`, `payer_dashboard.html`
- **Constants/enums:** UPPER_SNAKE_CASE — `DENIED`, `APPEALED`, `RESOLVED`, `WRITTEN_OFF`

### Patient Names
Always stored as `LAST, FIRST` format, uppercase. Apply `strip().upper()` on import. When matching, normalize by removing middle initials and handling `LAST FIRST` vs `FIRST LAST` variants.

### Money
Use `DECIMAL(10,2)` in the database. Default to `0.00`, never `NULL`, for payment fields. Always validate `total_payment == primary_payment + secondary_payment`.

### Dates
Excel source uses serial date format. Convert with `xlrd.xldate_as_datetime()` using epoch `date(1899, 12, 30) + serial_days`. Store as ISO DATE in SQLite.

### Imports
Batch insert 500 rows at a time. Deduplicate on `patient_name + service_date + scan_type + modality`.

## Critical Business Rules

These rules are non-negotiable and must be respected in all code:

| ID | Rule | Why It Matters |
|----|------|----------------|
| **BR-01** | C.A.P Exception: If `description = 'C.A.P'` and scan_type is CHEST/ABDOMEN/PELVIS with 3 records for same patient+date, it is NOT a duplicate | C.A.P = Chest/Abdomen/Pelvis, legitimately 3 scans in 1 visit |
| **BR-02** | PSMA Detection: If description contains 'PSMA' or 'Ga-68' or 'gallium', set `is_psma=TRUE` and use $8,046 rate (not $2,500 standard PET) | PSMA PET reimburses 3.47x standard PET |
| **BR-03** | Gado Premium: Add $200 to expected rate if `gado_used=TRUE` and modality is HMRI or OPEN | Gadolinium contrast adds cost |
| **BR-04** | Secondary Expected: M/M and CALOPTIMA carriers with primary but no secondary → flag for follow-up | ~$643K in missing secondary payments |
| **BR-05** | Timely Filing: Alert when unpaid claims approach `service_date + filing_deadline_days - 30` | Past-deadline = unrecoverable revenue |
| **BR-09** | Match Confidence: `score = 0.50*name + 0.30*date + 0.20*modality`. Auto-accept ≥0.95, review 0.80–0.95, reject <0.80 | Balances accuracy vs manual review burden |
| **BR-10** | SELFPAY Normalization: Normalize 'SELFPAY', 'SELF-PAY', 'CASH' → 'SELF PAY' on import | Prevents fragmented payer reporting |
| **BR-11** | Underpayment: Flag paid claims where `total_payment < expected_rate * 0.80` | 55.8% of paid claims are underpaid ($913K gap) |

## Payer Codes & Filing Deadlines

| Code | Name | Deadline (days) | Has Secondary |
|------|------|-----------------|---------------|
| M/M | Medicare/Medicaid | 365 | YES |
| CALOPTIMA | CalOptima | 180 | YES |
| FAMILY | Family Health Plan | 180 | NO |
| INS | Commercial Insurance | 180 | NO |
| W/C | Workers Comp | 180 | NO |
| ONE CALL | One Call Care Mgmt | 90 | NO |
| OC ADV | One Call Advanced | 180 | NO |

## Fee Schedule (Default Rates)

| Modality | Expected Rate | Notes |
|----------|--------------|-------|
| CT | $395 | |
| HMRI | $750 | +$200 with gado |
| PET | $2,500 | Standard. PSMA PET = $8,046 |
| BONE | $1,800 | Nuclear medicine |
| OPEN | $750 | +$200 with gado |
| DX | $250 | Diagnostic X-ray |

## X12 835 ERA Parsing Reference

835 files use `~` as segment delimiter and `*` as element delimiter:
- **ISA/GS/ST** — Envelope segments (metadata)
- **BPR** — Payment info: `BPR[01]`=method (CHK/ACH/FWT), `BPR[02]`=amount, `BPR[16]`=date
- **TRN** — Trace: `TRN[02]`=check/EFT number
- **N1*PR** — Payer name
- **CLP** — Claim: `CLP[01]`=claim_id, `CLP[02]`=status (1=primary, 2=secondary, 4=denied, 22=reversal), `CLP[03]`=billed, `CLP[04]`=paid
- **SVC** — Service line: `SVC[01]`=CPT code
- **CAS** — Adjustment: `CAS[01]`=group (CO/PR/OA/PI), `CAS[02]`=reason code, `CAS[03]`=amount
- Common reason codes: CO-4 (not covered), CO-16 (missing info), CO-45 (excess charges), PR-1 (deductible), PR-2 (coinsurance)

## Security & Compliance

- **NEVER commit OCMRI.xlsx or any file containing PHI to git**
- **NEVER add cloud service calls, external API calls, or telemetry**
- All data stays on the local machine/LAN — no exceptions
- Use synthetic/seed data for tests (`seed_data.py`)
- Optional SQLCipher encryption for `ocdr.db`
- Windows NTFS folder permissions for access control
- No credentials in source code — use `.env` file (in `.gitignore`)

## Sprint Build Order

Build features in this order (each sprint depends on the previous):

1. **Sprint 1:** F-00 (scaffolding), F-01 (Excel import), F-02 (835 parser), F-05 (underpayments), F-06 (filing deadlines), F-20 (backup)
2. **Sprint 2:** F-03 (auto-match), F-04 (denial tracking), F-07 (secondary follow-up), F-08 (duplicate detection)
3. **Sprint 3:** F-09 (payer alerts), F-11 (folder monitor), F-12 (CSV/PDF/OCR import)
4. **Sprint 4:** F-10 (physician statements), F-13 (PSMA tracking), F-16 (denial analytics), F-17 (payment matching)
5. **Sprint 5:** F-14 (Gado tracking), F-15 (physician analytics), F-18 (CSV export)
6. **Sprint 6:** F-19 (dashboard UI)

See `BUILD_SPEC.md` for full feature details, acceptance criteria, and API route specifications.

## Testing Strategy

- Use **pytest** as the test runner
- Place tests in `tests/` directory, named `test_*.py`
- Test with synthetic data only — never use real PHI
- Key areas requiring tests:
  - X12 835 parser (`test_835_parser.py`) — segment parsing, multi-CLP, multi-CAS, edge cases
  - Excel import — date conversion, column mapping, deduplication, batch inserts
  - Fuzzy matching — name normalization, confidence scoring, edge cases
  - Business rules — C.A.P exception, PSMA detection, SELFPAY normalization
  - Filing deadline computation — per-payer deadlines, alert thresholds
  - Underpayment detection — fee schedule comparison, gado premium
- Run `pytest tests/` before committing

## Common Pitfalls

1. **Excel serial dates** — Don't parse as integers. Use `xlrd.xldate_as_datetime()` with the 1900 date system (epoch: `1899-12-30`).
2. **C.A.P duplicates** — Three records for one visit (CHEST + ABDOMEN + PELVIS) is legitimate. Never flag as duplicate.
3. **PSMA vs standard PET** — PSMA PET reimburses ~$8,046 vs $2,500 standard. Use the correct fee schedule.
4. **ONE CALL payer** — Revenue dropped to $0 in 2025. The 90-day filing deadline is the shortest. Prioritize these claims.
5. **835 multi-segment** — A single CLP can have multiple SVC and CAS segments. Parse all of them, not just the first.
6. **Name matching** — Patients may appear as "LAST, FIRST" or "FIRST LAST". Normalize before fuzzy matching.
