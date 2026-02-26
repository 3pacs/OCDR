# OCDR — Claude Code Instructions

**What this is:** A local-first medical billing reconciliation system for imaging centers.
**Stack:** Flask + SQLAlchemy + SQLite + Bootstrap 5. Zero cloud. Zero internet required.
**Database:** `ocdr.db` (SQLite, ~7MB, ~10K+ records). All data stays on this machine.

---

## PROJECT STRUCTURE

```
app/
  __init__.py          # Flask app factory (create_app)
  config.py            # Config: DB path, folders, secret key
  models.py            # ALL models (14 tables) — single file, don't split
  ui/
    api.py             # ALL API endpoints (~100 routes) — /api/* prefix
    routes.py          # Page routes (HTML templates)
  matching/
    match_engine.py    # ERA→Billing auto-matching (core algorithm)
    match_memory.py    # SM-01/04/05/06: outcome tracking, aliases, CPT learning
    weight_optimizer.py # SM-01b/02: logistic regression weight optimization
    calibration.py     # SM-10: Platt scaling confidence calibration
  revenue/
    denial_tracker.py  # Denial queue, recoverability scoring
    denial_memory.py   # SM-03/12: denial outcome learning, pattern detection
    payment_patterns.py # SM-07: carrier payment analysis, fee suggestions
    physician_statements.py # F-10: statement generation
  import_engine/
    excel_importer.py  # .xlsx import with column auto-detection
    csv_importer.py    # .csv import (billing + schedule auto-detect)
    pdf_importer.py    # PDF table extraction
    schedule_importer.py # Folder-based schedule import
    validation.py      # Shared: date parsing, modality/carrier normalization, dedup
    column_learner.py  # SM-08: learned column mappings
    normalization_learner.py # SM-09: learned modality/carrier normalizations
  parser/
    era_835_parser.py  # ANSI X12 835 EDI parser
  analytics/
    denial_analytics.py, psma_tracker.py, gado_tracker.py, smart_insights.py
  core/
    payment_matching.py # Bank statement reconciliation
  monitor/
    folder_watcher.py  # Background folder polling for auto-import
  infra/
    backup_manager.py  # Database backup
  export/
    csv_exporter.py    # Billing/ERA CSV export
  llm/                 # (Sprint 13 — LLM integration layer)
templates/             # 21 Jinja2 HTML templates
static/css/style.css   # 1039 lines, Bootstrap 5 + custom dark theme
static/js/dashboard.js # Chart.js dashboard helpers
tests/                 # 6 test files, 221+ tests (pytest)
```

---

## CRITICAL RULES

### For ALL Models (Opus, Sonnet, Haiku)

1. **Run tests after every change:** `pytest tests/ -x -q`
2. **Never break existing endpoints.** API response format is consumed by the frontend.
3. **Never drop columns or tables.** Add new ones alongside old ones during migrations.
4. **Never load all records into memory.** Use `.paginate()`, `.limit()`, `.yield_per()`.
5. **Never use f-strings for HTML.** Use Jinja2 templates or `markupsafe.escape()`.
6. **Never store passwords in plaintext.** Use `werkzeug.security.generate_password_hash()`.
7. **Money is DECIMAL(10,2) in current schema.** New columns should use INTEGER cents.
8. **All dates are ISO 8601 (YYYY-MM-DD).** Parse with `validation.py:parse_date()`.
9. **Modality codes:** CT, HMRI, PET, BONE, OPEN, DX, GH. Normalize with `validation.py`.
10. **Carrier codes:** M/M, CALOPTIMA, FAMILY, INS, W/C, SELF PAY. Normalize with `validation.py`.

### For Sonnet/Haiku Specifically

- **Read the file before editing it.** Don't guess what's in a file.
- **Check ISSUES.md before fixing bugs.** The issue may already be documented with a suggested fix.
- **Check SPRINT_PLAN_PHASE2.md for context.** Your ticket has notes specific to your model tier.
- **Batch database operations in groups of 500.** `db.session.flush()` every 500 inserts.
- **Test with the real database.** `ocdr.db` has ~10K records. Don't just test on empty DBs.
- **Ask before creating new files.** Prefer editing existing files over creating new ones.
- **Don't refactor code you weren't asked to change.** Stay focused on the ticket.

---

## DATABASE TABLES (Quick Reference)

### Core Data
| Table | Purpose | Key Columns |
|-------|---------|-------------|
| billing_records | Patient billing claims | patient_name, service_date, modality, insurance_carrier, total_payment |
| era_payments | 835 remittance headers | filename, payment_amount, payment_date, payer_name |
| era_claim_lines | 835 claim details | patient_name_835, billed_amount, paid_amount, matched_billing_id |
| schedule_records | Appointment schedule | patient_name, scheduled_date, modality, status |

### Configuration
| Table | Purpose | Key Columns |
|-------|---------|-------------|
| payers | Insurance carrier config | code (PK), filing_deadline_days, expected_has_secondary |
| fee_schedule | Expected payment rates | payer_code, modality, expected_rate |
| physicians | Doctor reference | name (PK), physician_type, specialty |

### Smart Matching (SM-01 through SM-12)
| Table | Purpose |
|-------|---------|
| match_outcomes | Every confirm/reject decision with component scores |
| name_aliases | Confirmed patient name pairs (WILLIAM↔BILL) |
| learned_weights | Optimized weights per carrier/modality |
| learned_cpt_modality | CPT code → modality mappings |
| denial_outcomes | Appeal results for recovery rate learning |
| column_aliases_learned | Import column header → DB field mappings |
| normalization_learned | Modality/carrier normalization expansions |

---

## COMMON TASKS

### Adding a new API endpoint
1. Add route in `app/ui/api.py` under the appropriate section
2. Use `@api_bp.route("/your/endpoint")` decorator
3. Return `jsonify(data)` with appropriate status code
4. Add test in `tests/test_api_integration.py`

### Adding a new database column
1. Add column to model in `app/models.py`
2. If Flask-Migrate is set up: `flask db migrate -m "description"` then `flask db upgrade`
3. If no migrations yet: column will be added on next `db.create_all()` (new DBs only)
4. For existing DBs without migrations: write a manual ALTER TABLE migration

### Adding a new template page
1. Add route in `app/ui/routes.py`
2. Create template in `templates/` extending `base.html`
3. Use `{% block content %}` for page content, `{% block scripts %}` for JS
4. All pages use the same nav, style, and `fetchJSON()` helper from base.html

### Running the app
```bash
python run.py              # Development server on http://localhost:5000
gunicorn -w 4 "app:create_app()"  # Production
pytest tests/ -x -q        # Run tests (stop on first failure)
```

---

## KNOWN ISSUES (See ISSUES.md for full list)

**CRITICAL:** XSS in physician statements (Issue #1), no auth (Issue #2)
**HIGH:** Full table scans in denial/deadline/underpayment endpoints (Issues #3-6)
**HIGH:** N+1 queries in match results and EraPayment listing (Issues #7-8)
**MEDIUM:** Thread safety in folder monitor (Issue #11), memory leak (Issue #12)

---

## SPRINT STATUS

| Sprint | Status | Scope |
|--------|--------|-------|
| 1-6 | COMPLETE | Core billing, ERA, matching, denials, analytics, UI |
| 7-10 | COMPLETE | Smart matching (SM-01 through SM-12) |
| 11 | PLANNED | Database schema hardening (see SPRINT_PLAN_PHASE2.md) |
| 12 | PLANNED | Performance & security fixes |
| 13 | PLANNED | LLM integration layer |
| 14 | PLANNED | Advanced workflows (appeal letters, aging, lifecycle) |
| 15 | PLANNED | Production polish (auth, logging, deployment) |

---

## LLM INTEGRATION NOTES

This app will eventually connect to a local LLM (Ollama/llama.cpp). The integration design:

1. **Schema context** (~500 tokens) is auto-generated and injected into every LLM prompt
2. **Structured query API** (`/api/query`) accepts JSON query specs — safer than raw SQL
3. **Result formatter** converts query results into natural language summaries
4. **The LLM never writes SQL directly** — it generates structured query JSON, which the query engine validates and executes

When building the LLM layer (Sprint 13):
- Whitelist all table and column names. Reject anything not in the whitelist.
- Parameterize all values. Never concatenate user input into SQL.
- The local LLM bridge should call Ollama HTTP API at `localhost:11434`.
- Don't import any LLM libraries. Use HTTP requests only.

---

## TESTING

```bash
# Run all tests
pytest tests/ -x -q

# Run specific test file
pytest tests/test_smart_matching.py -v

# Run with coverage
pytest tests/ --cov=app --cov-report=term-missing

# Current: 221 tests, all passing
# Target after Phase 2: 300+ tests
```

Test files:
- `test_validation.py` — Import validation, normalization, dedup
- `test_importers.py` — Excel/CSV/PDF importers
- `test_835_parser.py` — 835 EDI parser
- `test_match_engine.py` — Auto-match scoring
- `test_smart_matching.py` — Smart matching features (SM-01 to SM-12)
- `test_api_integration.py` — API endpoint integration
