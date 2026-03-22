# LLM Continuation Instructions

Instructions for any LLM (Claude, GPT, etc.) continuing development on this codebase.

---

## 1. Read These Files First

1. **CLAUDE.md** — Architecture, column mapping, data gotchas (G-01 to G-14), session history
2. **SETUP.md** — How to run, test, and operate the system
3. **TASKS.md** — Auto-generated operational state (if present; created at runtime)
4. **This file** — What's done, what's not, and how to avoid known pitfalls

---

## 2. Architecture (DO NOT trust BUILD_SPEC.md)

BUILD_SPEC.md says Flask + SQLite. The actual stack is:

| Layer | Technology | Key Files |
|-------|-----------|-----------|
| **Backend** | FastAPI + asyncpg | `backend/app/main.py`, `backend/app/api/routes/` |
| **Database** | PostgreSQL 16 | `backend/app/models/`, `backend/app/db/session.py` |
| **Frontend** | React 18 + React Bootstrap + Recharts | `frontend/src/` |
| **Matching** | 14-pass fuzzy matcher + rapidfuzz | `backend/app/matching/auto_matcher.py` |
| **Parsing** | X12 835 parser, OCMRI Excel ingestor | `backend/app/parsing/`, `backend/app/ingestion/` |

### Key Patterns
- **Async everywhere**: All DB operations use `AsyncSession` via `get_db` dependency
- **Validation on import**: `backend/app/analytics/data_validation.py` validates against public CARC/CPT/X12 codes
- **Write-off filtering**: `backend/app/revenue/writeoff_filter.py` — ALL dashboard queries MUST use `not_written_off()` to exclude terminal claims
- **Auto-seeding**: `backend/app/db/seed_data.py` runs on startup (payers, fee schedule, business tasks)
- **Background jobs**: APScheduler runs at 6AM (pipeline), 6:30AM (auto-improvements), 7AM (task generation)

---

## 3. Known Working State (as of 2026-03-18)

### All 38 API endpoints tested and passing:
- Health, Import (4), Matching (4), Denials (3), Underpayments (2), Filing (2)
- Secondary (2), ERA (1), Analytics (12), Insights (3), Pipeline (2), Tasks (3)

### Sample data loaded:
- 200 billing records, 143 ERA claim lines across 6 835 files
- 100% match rate (133 Pass 0, 4 Pass 9, 6 auto-created)
- Sample data generator: `scripts/generate_sample_data.py`
- Endpoint test suite: `scripts/test_all_endpoints.sh`

---

## 4. Bugs Fixed in This Session

| Bug | Root Cause | Fix |
|-----|-----------|-----|
| `denial_summary` 500 error | `func.coalesce()` GROUP BY generates duplicate parameter bindings in PostgreSQL | Use a labeled column variable for both SELECT and GROUP BY |
| `underpayment_summary` 500 | Missing `or_` import in `underpayment_detector.py` | Added import; replaced inline filter with `not_written_off()` |
| `filing_deadline_alerts` 500 | Same missing import issue in `filing_deadlines.py` | Replaced inline filter with `not_written_off()` |
| `session_report` 500 | Same coalesce GROUP BY bug in `session_log.py` | Applied same fix pattern |
| Payer detail 404 for `M/M` | Slash in carrier code breaks path parameter | Changed to `{carrier:path}` |
| `reconciliation_dashboard` uses `BillingRecord.billed_amount` | Column doesn't exist | Replaced with `total_payment + extra_charges` expression |

### Systemic Lesson
**NEVER use `func.coalesce()` twice with the same expression in SELECT + GROUP BY.** Instead:
```python
# WRONG — PostgreSQL sees these as different expressions:
select(func.coalesce(Col.x, "default")).group_by(func.coalesce(Col.x, "default"))

# RIGHT — use a labeled column:
col = func.coalesce(Col.x, "default").label("alias")
select(col).group_by(col)
```

---

## 5. What's NOT Done (prioritized)

### High Priority
| Feature | ID | Notes |
|---------|-----|-------|
| **Payment Reconciliation** | F-17 | Bank statement matching (check/EFT → ERA → billing). No code exists. Needs bank statement parser + reconciliation engine. |
| **CSV Export Bridge** | F-18 | Scheduled export for Excel Power Query. Need cron job + CSV writer for key tables. |
| **Physician Statements** | F-10 | PDF invoice generation. Need PDF template + monthly aggregation query. |

### Medium Priority
| Feature | ID | Notes |
|---------|-----|-------|
| **Full Folder Monitor** | F-11 | Only EOB scanner exists. Need watchdog-based daemon for auto-import. |
| **CSV/PDF Import** | F-12 | Only stubs exist. Need CSV parser + PDF/OCR parser (pytesseract installed). |

### Low Priority / Nice-to-Have
- Error boundary component for React (any page crash kills the whole app)
- Auth token expiry handling (401 interceptor)
- TypeScript migration
- Extract `formatMoney()` and status badges to shared utilities
- Sortable data tables
- Date range pickers on analytics pages

---

## 6. Data Gotchas (Critical — Read Before Making Changes)

See CLAUDE.md for the full list (G-01 to G-14). The most important:

- **G-05**: Topaz prefix encoding — `MOD(PatientID, 10000000)` extracts real patient ID. Prefix 1=primary, 2=secondary, 7=copay.
- **G-01**: Hispanic married/maiden names — ERA and billing can have completely different last names for the same patient. Matcher trusts ID over name.
- **G-06**: ERA claim IDs are zero-padded (00061501 vs 61501)
- **G-07**: Chart number ≠ Topaz ID. No formula. Must use crosswalk.
- **G-13**: Re-running matcher gives "0 new" because it skips already-matched claims. Use force re-match.

---

## 7. How to Add New Features

### New API Endpoint
1. Add route in the appropriate `backend/app/api/routes/` file
2. Keep async, use `get_db` dependency for database access
3. Use `not_written_off()` filter for any dashboard/actionable queries
4. Add to `scripts/test_all_endpoints.sh` for regression testing

### New Frontend Page
1. Create page in `frontend/src/pages/`
2. Add route in `frontend/src/App.js`
3. Add nav link in `frontend/src/components/Layout.js` (Revenue or Analytics dropdown)
4. Use `api` import from `../services/api` for HTTP calls
5. Follow existing patterns: `useState`, `useEffect`, `useCallback`

### New Database Column
1. Add to the SQLAlchemy model in `backend/app/models/`
2. Add migration in `main.py` lifespan function (ADD COLUMN IF NOT EXISTS)
3. Update any queries that need the new column

### New Payer or Fee Schedule
1. Add to `PAYERS` or `FEE_SCHEDULES` in `backend/app/db/seed_data.py`
2. System auto-seeds on next startup (checks for existence)

---

## 8. Testing Checklist

Before pushing changes:

```bash
# 1. Run endpoint test suite
bash scripts/test_all_endpoints.sh
# Expect: PASS=38 FAIL=0

# 2. Check Python imports
PYTHONPATH=/path/to/OCDR python3 -c "from backend.app.main import app; print('OK')"

# 3. Run existing unit tests
PYTHONPATH=/path/to/OCDR python3 -m pytest backend/tests/ -v

# 4. Test data loading
python scripts/generate_sample_data.py
curl -X POST http://localhost:8000/api/import/excel -F 'file=@data/excel/OCMRI_sample.xlsx'
curl -X POST http://localhost:8000/api/matching/run
```

---

## 9. Environment Variables Reference

| Variable | Default | Purpose |
|----------|---------|---------|
| DATABASE_URL | postgresql+asyncpg://ocmri:ocmri_secret@localhost:5432/ocmri | Async DB URL |
| DATABASE_URL_SYNC | postgresql://ocmri:ocmri_secret@localhost:5432/ocmri | Sync DB URL (for Alembic) |
| DUCKDB_PATH | /app/data/duckdb/analytics.duckdb | DuckDB analytics file |
| DATA_DIR | /app/data | Root data directory |
| EXCEL_DIR | /app/data/excel | Excel upload directory |
| EOBS_DIR | /app/data/eobs | EOB/835 file directory |
| PYTHONPATH | Project root | Must be set for `backend.app` imports |
| REACT_APP_API_URL | http://localhost:8000 | Frontend → backend URL |
