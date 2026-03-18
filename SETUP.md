# OCMRI Billing Reconciliation System — Setup & Operations Guide

## Quick Start

### Option A: Docker (recommended for production)

```bash
docker-compose up
# Backend:  http://localhost:8000  (API docs: /docs)
# Frontend: http://localhost:3000
# Postgres: localhost:5432, db=ocmri, user=ocmri, pass=ocmri_secret
```

### Option B: Local Development (no Docker)

```bash
# 1. Start PostgreSQL
sudo pg_ctlcluster 16 main start  # or: sudo service postgresql start

# 2. Create database (one-time)
sudo -u postgres psql -c "CREATE USER ocmri WITH PASSWORD 'ocmri_secret';"
sudo -u postgres createdb -O ocmri ocmri

# 3. Install dependencies
pip install -r backend/requirements.txt
cd frontend && npm install && cd ..

# 4. Start backend
export DATABASE_URL="postgresql+asyncpg://ocmri:ocmri_secret@localhost:5432/ocmri"
export DATABASE_URL_SYNC="postgresql://ocmri:ocmri_secret@localhost:5432/ocmri"
export DUCKDB_PATH="$(pwd)/data/duckdb/analytics.duckdb"
export DATA_DIR="$(pwd)/data"
export EXCEL_DIR="$(pwd)/data/excel"
export EOBS_DIR="$(pwd)/data/eobs"
export PYTHONPATH="$(pwd)"
uvicorn backend.app.main:app --host 0.0.0.0 --port 8000 &

# 5. Start frontend
cd frontend
REACT_APP_API_URL=http://localhost:8000 npx react-scripts start &
```

### Generate Sample Data (for testing)

```bash
python scripts/generate_sample_data.py
# Creates data/excel/OCMRI_sample.xlsx and data/eobs/*.835 files

# Load via API:
curl -X POST http://localhost:8000/api/import/excel -F 'file=@data/excel/OCMRI_sample.xlsx'
curl -X POST http://localhost:8000/api/matching/run

# Or upload via the web UI at http://localhost:3000/import
```

### Verify Everything Works

```bash
bash scripts/test_all_endpoints.sh
# Should show: PASS=38  FAIL=0
```

---

## Daily Operations Workflow

### Morning Routine (in order)
1. **Review today's schedule** — Check `/tasks` page for today's checklist
2. **Import OCMRI data** — Upload OCMRI.xlsx via `/import` page
3. **Import ERA 835 files** — Upload electronic remittances via `/import`
4. **Run auto-matcher** — Go to `/matching`, click run (or POST `/api/matching/run`)
5. **Post payments to Topaz** — Use matched results to post in Topaz billing system
6. **Review denials** — Check `/denials` for new denied claims

### Weekly Tasks
- **Monday**: Review payer monitor alerts (`/payer-monitor`)
- **Tuesday**: Bank deposits
- **Wednesday**: Follow up on appeals (`/denials` → filter "appealed")
- **Friday (bi-weekly)**: Payroll, banking reconciliation

### Monthly Tasks
- **1st**: Pay supply bills (PET, CT, Gado contrast), review pipeline improvements
- **5th**: Research billing (Jhangiani, Beach)
- **15th**: SBA loan payment
- **28th**: All-account bank reconciliation

---

## Data Import Guide

### OCMRI Excel Import
The system auto-detects the column layout (22 or 23 columns). The "Current" sheet is imported by default.

**Key columns:**
| Column | Field | Notes |
|--------|-------|-------|
| A | Patient Name | Primary name (Candelis) |
| G | Service Date | Date of scan |
| E | Insurance | Payer code (M/M, INS, etc.) |
| F | Type/Modality | CT, HMRI, PET, BONE, OPEN, DX |
| M | Chart ID | Clinic jacket/chart number |
| V | Patient ID | Topaz billing system ID |

### ERA 835 Import
Upload `.835`, `.edi`, or `.txt` files containing X12 835 remittance data. The parser extracts payment info, claim lines, CARC/RARC codes, and service dates.

### Matching
After importing both billing records and ERA files, run the auto-matcher:
- **Pass 0**: Matches by Topaz ID (highest confidence)
- **Passes 1-9**: Progressively looser name/date/amount matching
- **Pass 10**: Auto-creates stub billing records for unmatched ERA claims
- Use "Force Re-Match All" to clear and re-run from scratch

---

## Database Access

### PostgreSQL Direct Access
```
Host: localhost:5432
Database: ocmri
User: ocmri
Password: ocmri_secret
```

**Tools:**
- **DBeaver**: Free, cross-platform. Connect → PostgreSQL → enter credentials above
- **pgAdmin**: Free, web-based. Connect to localhost:5432
- **psql**: `PGPASSWORD=ocmri_secret psql -h localhost -U ocmri -d ocmri`
- **Excel Power Query**: Requires PostgreSQL ODBC driver, then Data → From Database → PostgreSQL

### Key Tables
| Table | Records | Purpose |
|-------|---------|---------|
| billing_records | Main data | Patient scans, payments, denials |
| era_payments | ERA headers | 835 payment batches |
| era_claim_lines | ERA claims | Individual claim lines from 835 |
| payers | Reference | Insurance carriers + filing deadlines |
| fee_schedule | Reference | Expected rates by modality |
| business_tasks | Config | Task templates + action steps |
| task_instances | Daily | Today's task checklist |

---

## Troubleshooting

### Common Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| "0 new matches" after re-import | Matcher skips already-matched claims | Use "Force Re-Match All" button |
| Name mismatches (Hispanic names) | Married vs maiden name across systems | System uses token_set_ratio; see CLAUDE.md G-01 |
| ERA claim IDs don't match | Topaz prefix encoding (10XXXXX) | System auto-decodes; see CLAUDE.md G-05 |
| Import shows errors | Missing required fields in Excel | Check patient_name, doctor, scan, insurance, modality, date |
| Pages show "Loading..." forever | Backend timeout or crash | Check backend logs, restart uvicorn |

### Resetting the Database
```bash
PGPASSWORD=ocmri_secret psql -h localhost -U ocmri -d ocmri -c "
  TRUNCATE billing_records, era_payments, era_claim_lines,
           task_instances, insight_logs CASCADE;
"
# Then re-import data
```
