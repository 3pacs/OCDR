# OCDR Phase 2 Sprint Plan — Sprints 11-15

**Version:** 1.0 | **Created:** 2026-02-26 | **Planned by:** Claude Opus 4.6
**Prerequisite:** Sprints 7-10 (Smart Matching) — COMPLETED
**Goal:** Database hardening, performance, security, LLM integration, production readiness

---

## PHASE 2 OVERVIEW

| Sprint | Name | Duration | Focus |
|--------|------|----------|-------|
| **11** | Schema Hardening | 2 weeks | Database redesign, FK enforcement, lookup tables, migrations |
| **12** | Performance & Safety | 2 weeks | Fix all HIGH issues, N+1 queries, memory leaks, XSS |
| **13** | LLM Integration Layer | 2 weeks | Natural language query interface, context builder, local LLM bridge |
| **14** | Advanced Workflows | 2 weeks | Automated appeal letters, batch operations, scheduled reports |
| **15** | Production Polish | 1 week | Auth, error handling, logging, deployment hardening |

---

## Sprint 11: Schema Hardening & Database Redesign

**Duration:** 2 weeks | **Goal:** Fix structural database debt without breaking the running system
**Reference:** DATABASE_REDESIGN.md for full analysis

### Tickets

| Ticket | Title | Priority | Est Hours | Depends On | Files |
|--------|-------|----------|-----------|------------|-------|
| DB-01 | **Install Flask-Migrate, initialize Alembic** | P0 | 3 | — | `migrations/`, `app/__init__.py`, `requirements.txt` |
| DB-02 | **Create lookup tables: modalities, scan_types** | P0 | 4 | DB-01 | `app/models.py`, migration script |
| DB-03 | **Create cpt_codes and cas_reason_codes reference tables** | P0 | 4 | DB-01 | `app/models.py`, migration script, seed data |
| DB-04 | **Add FK columns to billing_records** (carrier_code, modality_code, scan_type_code) | P0 | 6 | DB-02 | `app/models.py`, migration script |
| DB-05 | **Backfill migration: populate new FK columns from existing free-text** | P0 | 8 | DB-04 | `migrations/backfill_fks.py`, `app/import_engine/validation.py` |
| DB-06 | **Add junction tables: era_claim_cpt_codes, era_claim_adjustments** | P1 | 6 | DB-03 | `app/models.py`, migration script |
| DB-07 | **Backfill junction tables from comma-separated columns** | P1 | 6 | DB-06 | `migrations/backfill_junctions.py` |
| DB-08 | **Add FK constraint on era_claim_lines.matched_billing_id** | P0 | 3 | DB-01 | `app/models.py`, migration script |
| DB-09 | **Add unique constraints** on fee_schedule(payer,modality), learned_weights(carrier,modality) | P1 | 3 | DB-01 | `app/models.py`, migration script |
| DB-10 | **Add composite indexes** for dashboard, denial, matching queries | P1 | 4 | DB-04 | migration script |
| DB-11 | **Add updated_at and deleted_at audit columns** to core tables | P2 | 4 | DB-01 | `app/models.py`, migration script |
| DB-12 | **Fee schedule v2: gado_premium_cents column, effective_date** | P2 | 6 | DB-02 | `app/models.py`, `app/ui/api.py` |
| DB-13 | **Dual-write: update all importers to populate new + old columns** | P0 | 8 | DB-05 | All importers, `app/ui/api.py` |
| DB-T01 | **Tests: migration scripts, FK enforcement, backfill correctness** | P0 | 8 | all above | `tests/test_migrations.py` |

**Sprint 11 Total: 73 hours**

### Acceptance Criteria
- [ ] Flask-Migrate initialized; `flask db upgrade` runs cleanly on fresh and existing DBs
- [ ] All new FK columns populated for existing data (zero NULLs on backfill)
- [ ] `matched_billing_id` FK enforced — setting invalid ID raises IntegrityError
- [ ] Junction tables contain all CPT and CAS data from existing comma-separated fields
- [ ] No unique constraint violations after dedup migration
- [ ] All 221+ existing tests still pass
- [ ] New migration tests verify up/down for every migration

### Notes for Lower-Level Models (Sonnet/Haiku)
```
IMPORTANT: When working on Sprint 11 tickets:
- NEVER drop existing columns. Only ADD new ones alongside old ones.
- ALWAYS run `flask db migrate` then `flask db upgrade` to test.
- ALWAYS run `pytest tests/` after every migration to verify nothing breaks.
- The backfill scripts must handle NULL values gracefully (skip, don't crash).
- Use batch operations (500 rows per commit) for backfill — don't load all at once.
- Test with the actual ocdr.db file (6.7MB, ~10K+ records) not just empty DBs.
```

---

## Sprint 12: Performance & Safety

**Duration:** 2 weeks | **Goal:** Fix all HIGH/CRITICAL issues from ISSUES.md
**Reference:** ISSUES.md for full issue descriptions

### Tickets

| Ticket | Title | Priority | Est Hours | Depends On | Files |
|--------|-------|----------|-----------|------------|-------|
| PERF-01 | **Fix denial queue: SQL-level pagination, JOIN fee_schedule** | P0 | 8 | DB-10 | `app/revenue/denial_tracker.py`, `app/ui/api.py` |
| PERF-02 | **Fix filing deadlines: compute deadline in SQL, paginate at DB** | P0 | 6 | DB-10 | `app/ui/api.py` (lines 195+) |
| PERF-03 | **Fix underpayment summary: SQL JOIN instead of Python loop** | P0 | 6 | DB-10 | `app/ui/api.py` (_get_underpayment_summary) |
| PERF-04 | **Fix N+1 in match results: batch-load billing records** | P1 | 4 | — | `app/matching/match_engine.py` (get_match_results) |
| PERF-05 | **Fix N+1 in EraPayment.to_dict(): use subquery count** | P1 | 3 | — | `app/models.py` (EraPayment.to_dict) |
| PERF-06 | **Fix match engine O(N*M): pre-load candidates by date window** | P1 | 8 | — | `app/matching/match_engine.py` (run_matching) |
| PERF-07 | **Fix CSV export: streaming with yield_per(1000)** | P2 | 4 | — | `app/export/csv_exporter.py` |
| PERF-08 | **Cap per_page parameter to max 500 on all endpoints** | P2 | 3 | — | `app/ui/api.py` |
| SEC-01 | **Fix XSS in physician statements: use Jinja2 auto-escaping** | P0 | 4 | — | `app/revenue/physician_statements.py` |
| SEC-02 | **Escape LIKE wildcards in user search input** | P1 | 2 | — | `app/ui/api.py`, `app/revenue/physician_statements.py` |
| SEC-03 | **Validate file extensions on all upload endpoints** | P1 | 3 | — | `app/ui/api.py` |
| SEC-04 | **Fix hardcoded SECRET_KEY: require in production** | P2 | 2 | — | `app/config.py` |
| FIX-01 | **Fix resolve_denial payment inconsistency** (Issue #13) | P1 | 3 | — | `app/revenue/denial_tracker.py` |
| FIX-02 | **Fix folder monitor thread safety** (Issue #11) | P2 | 4 | — | `app/monitor/folder_watcher.py` |
| FIX-03 | **Fix monitor memory leak: cap error list** (Issue #12) | P2 | 2 | — | `app/monitor/folder_watcher.py` |
| FIX-04 | **Fix monitor file overwrite: timestamp suffix** (Issue #21) | P2 | 2 | — | `app/monitor/folder_watcher.py` |
| FIX-05 | **Replace datetime.utcnow() with datetime.now(UTC)** (Issue #19) | P3 | 2 | — | All files |
| FIX-06 | **Replace Model.query.get() with db.session.get()** (Issue #14) | P3 | 3 | — | All files |
| PERF-T01 | **Benchmark tests: verify query count and memory for key endpoints** | P1 | 6 | PERF-01 to PERF-06 | `tests/test_performance.py` |

**Sprint 12 Total: 75 hours**

### Acceptance Criteria
- [ ] Denial queue endpoint responds in <200ms with 10K records (was unbounded)
- [ ] Dashboard load does zero full-table scans (verified by SQL logging)
- [ ] Match engine run_matching uses ≤2 queries regardless of claim count
- [ ] XSS payload in physician name renders as escaped text, not executable
- [ ] All upload endpoints reject wrong file extensions with 400 error
- [ ] Monitor runs for 1 hour under file churn without memory growth
- [ ] All 221+ existing tests + new perf tests pass

### Notes for Lower-Level Models (Sonnet/Haiku)
```
IMPORTANT: When working on Sprint 12 tickets:
- For PERF tickets: the goal is to move computation from Python to SQL.
  Instead of `records = Model.query.all()` followed by Python filtering,
  use `Model.query.filter(...).order_by(...).paginate(...)`.
- For N+1 fixes: collect all IDs first, then batch-load with `.in_(ids)`.
- For SEC-01: use markupsafe.escape() on every user-supplied value.
  Import: `from markupsafe import escape`
  Usage: `escape(physician_name)` before inserting into HTML string.
- For FIX-02: wrap all global state access with `threading.Lock()`.
  Pattern:
    _lock = threading.Lock()
    with _lock:
        _monitor_status["last_scan"] = datetime.now(UTC)
- ALWAYS run the full test suite after each fix.
- NEVER change the API response format — only change how data is fetched.
```

---

## Sprint 13: LLM Integration Layer

**Duration:** 2 weeks | **Goal:** Build the bridge between OCDR and a local LLM
**Architecture:** OCDR exposes a structured query API; LLM translates natural language to API calls or SQL

### Design Philosophy

The LLM integration has three layers:

```
┌─────────────────────────────────────────┐
│  Layer 3: LLM Interface (future)        │
│  - Local LLM (Ollama/llama.cpp)         │
│  - Prompt templates with schema context  │
│  - Natural language → structured query   │
└─────────────┬───────────────────────────┘
              │
┌─────────────▼───────────────────────────┐
│  Layer 2: Query Engine (Sprint 13)      │
│  - Structured query language             │
│  - Safe SQL generation from parameters   │
│  - Result formatting for LLM consumption │
│  - Context builder (schema + recent data)│
└─────────────┬───────────────────────────┘
              │
┌─────────────▼───────────────────────────┐
│  Layer 1: Data Layer (Sprints 11-12)    │
│  - Normalized schema with FKs           │
│  - Composite indexes                     │
│  - Audit columns                         │
└─────────────────────────────────────────┘
```

Sprint 13 builds **Layer 2** — the query engine that any LLM can drive.

### Tickets

| Ticket | Title | Priority | Est Hours | Depends On | Files |
|--------|-------|----------|-----------|------------|-------|
| LLM-01 | **Schema descriptor: auto-generate schema context for LLM prompts** | P0 | 6 | DB-04 | `app/llm/schema_context.py` |
| LLM-02 | **Structured query API: /api/query endpoint accepting JSON query specs** | P0 | 12 | — | `app/llm/query_engine.py`, `app/ui/api.py` |
| LLM-03 | **Safe SQL builder: convert structured queries to parameterized SQL** | P0 | 10 | LLM-02 | `app/llm/sql_builder.py` |
| LLM-04 | **Result formatter: convert query results to LLM-friendly text** | P1 | 6 | LLM-02 | `app/llm/result_formatter.py` |
| LLM-05 | **Context builder: summarize recent data for LLM prompt context** | P1 | 8 | LLM-01 | `app/llm/context_builder.py` |
| LLM-06 | **Prompt templates: pre-built prompts for common billing questions** | P1 | 6 | LLM-05 | `app/llm/prompts/` |
| LLM-07 | **Chat API endpoint: /api/chat for conversational query interface** | P1 | 8 | LLM-02, LLM-04 | `app/ui/api.py`, `app/llm/chat_handler.py` |
| LLM-08 | **Chat UI: simple chat interface in the web app** | P2 | 8 | LLM-07 | `templates/chat.html`, `app/ui/routes.py` |
| LLM-09 | **Local LLM bridge: Ollama/llama.cpp integration** | P2 | 8 | LLM-07 | `app/llm/local_bridge.py` |
| LLM-10 | **Fallback mode: structured query forms when no LLM available** | P2 | 6 | LLM-02 | `templates/query_builder.html` |
| LLM-T01 | **Tests: query engine, SQL builder (injection prevention), formatter** | P0 | 8 | all above | `tests/test_llm_query.py` |

**Sprint 13 Total: 86 hours**

### Structured Query API Design

The `/api/query` endpoint accepts a JSON query spec that an LLM can generate:

```json
{
  "action": "aggregate",
  "table": "billing_records",
  "measures": ["sum:total_payment", "count:id", "avg:total_payment"],
  "dimensions": ["insurance_carrier", "modality"],
  "filters": [
    {"field": "service_date", "op": ">=", "value": "2025-01-01"},
    {"field": "total_payment", "op": ">", "value": 0},
    {"field": "insurance_carrier", "op": "in", "value": ["M/M", "CALOPTIMA"]}
  ],
  "order_by": [{"field": "sum:total_payment", "direction": "desc"}],
  "limit": 20
}
```

This is safer than raw SQL because:
- Only whitelisted tables/columns allowed
- Only whitelisted operations (=, !=, >, <, >=, <=, in, like, between)
- All values are parameterized (no injection)
- Results are automatically formatted

### Schema Context for LLM Prompts

```python
# Auto-generated, ~500 tokens, included in every LLM prompt
SCHEMA_CONTEXT = """
You are querying a medical billing database. Tables:

billing_records: Patient billing claims
  - id, patient_name, referring_doctor, scan_type, modality, insurance_carrier
  - service_date, primary_payment, secondary_payment, total_payment
  - gado_used (bool), is_psma (bool), denial_status, denial_reason_code

era_payments: Insurance remittance (835 files)
  - id, filename, check_eft_number, payment_amount, payment_date, payer_name

era_claim_lines: Individual claims from ERA files
  - id, era_payment_id, claim_id, patient_name_835, service_date_835
  - billed_amount, paid_amount, cpt_code, cas_reason_code
  - matched_billing_id (links to billing_records.id)

payers: Insurance carrier configuration
  - code (PK), display_name, filing_deadline_days

fee_schedule: Expected payment rates
  - payer_code, modality, expected_rate

Modality codes: CT, HMRI (High-Field MRI), PET, BONE, OPEN, DX, GH
Carrier codes: M/M (Medicare/Medicaid), CALOPTIMA, FAMILY, INS, W/C, SELF PAY
Money is in dollars (decimal). Dates are YYYY-MM-DD.
"""
```

### Example LLM Interactions

```
User: "How much did Medicare pay us last month?"
LLM generates → {"action": "aggregate", "table": "billing_records",
                  "measures": ["sum:total_payment"],
                  "filters": [{"field": "insurance_carrier", "op": "=", "value": "M/M"},
                              {"field": "service_date", "op": ">=", "value": "2026-01-01"},
                              {"field": "service_date", "op": "<", "value": "2026-02-01"}]}
Result → "Medicare paid $142,350.00 across 847 claims in January 2026."

User: "Which carriers are underpaying us on MRI?"
LLM generates → compare actual payments vs fee_schedule for HMRI modality
Result → "CALOPTIMA is paying 72% of expected rate on HMRI ($450 avg vs $625 expected).
          FAMILY is paying 85% ($531 vs $625). M/M is on target at 97%."

User: "What's our top denial reason this quarter?"
LLM generates → aggregate denial_reason_code with count, group by code
Result → "CO-4 (inconsistent procedure code) accounts for 34% of denials (89 claims, $67K).
          CO-45 (charges exceed fee schedule) is second at 22% (57 claims, $41K)."
```

### Acceptance Criteria
- [ ] `/api/query` accepts JSON specs and returns correct results
- [ ] SQL injection impossible via structured query API (fuzz-tested)
- [ ] Schema context auto-generated and <600 tokens
- [ ] Chat endpoint works with or without local LLM (fallback to structured forms)
- [ ] At least 10 prompt templates cover common billing questions
- [ ] All 221+ existing tests + new LLM tests pass

### Notes for Lower-Level Models (Sonnet/Haiku)
```
IMPORTANT: When working on Sprint 13 tickets:
- The query engine must NEVER execute raw user-provided SQL.
  Always use parameterized queries via SQLAlchemy.
- Whitelist approach: only allow known table names and column names.
  Reject anything not in the whitelist.
- The sql_builder.py must validate every field name against models.
  Pattern: ALLOWED_FIELDS = {"billing_records": ["id", "patient_name", ...]}
- For the LLM bridge (LLM-09): use HTTP calls to Ollama API at localhost:11434.
  Don't import any LLM libraries directly.
- The chat UI should be simple: a text input and a results area.
  No complex frontend framework needed — vanilla JS like all other pages.
- Tests MUST include SQL injection attempts in filter values.
  Test: {"field": "'; DROP TABLE billing_records;--", "op": "=", "value": "x"}
```

---

## Sprint 14: Advanced Workflows

**Duration:** 2 weeks | **Goal:** Automate repetitive RCM workflows
**These features build on the schema + LLM foundation from Sprints 11-13.**

### Tickets

| Ticket | Title | Priority | Est Hours | Depends On | Files |
|--------|-------|----------|-----------|------------|-------|
| WF-01 | **Appeal letter generator: template-based letters from denial data** | P0 | 10 | — | `app/workflows/appeal_letters.py`, `templates/appeal_letter.html` |
| WF-02 | **Batch denial appeal: select multiple, generate letters in bulk** | P1 | 6 | WF-01 | `app/ui/api.py`, `templates/denial_queue.html` |
| WF-03 | **Scheduled reports: daily/weekly email-ready HTML summaries** | P1 | 8 | — | `app/workflows/scheduled_reports.py` |
| WF-04 | **Aging report: claims aged 30/60/90/120+ days by carrier** | P1 | 6 | — | `app/analytics/aging_report.py`, `templates/aging.html` |
| WF-05 | **Payment posting automation: auto-match ERA payments to billing** | P1 | 8 | PERF-06 | `app/workflows/auto_posting.py` |
| WF-06 | **Claim status workflow: track SUBMITTED→PENDING→PAID/DENIED lifecycle** | P2 | 8 | DB-11 | `app/models.py`, `app/workflows/claim_lifecycle.py` |
| WF-07 | **Duplicate claim detection: ML-free similarity scoring for potential dupes** | P2 | 6 | — | `app/analytics/duplicate_detector.py` |
| WF-08 | **Provider credentialing alerts: track credential expiry dates** | P2 | 6 | — | `app/models.py`, `app/workflows/credentialing.py` |
| WF-09 | **Payer contract tracker: store contracted rates, compare vs actual** | P2 | 8 | DB-12 | `app/revenue/contract_tracker.py` |
| WF-T01 | **Tests: appeal letters, aging, auto-posting, lifecycle** | P0 | 8 | all above | `tests/test_workflows.py` |

**Sprint 14 Total: 74 hours**

### Acceptance Criteria
- [ ] Appeal letter generated with correct patient info, dates, denial codes, and payer address
- [ ] Batch appeal generates a ZIP of PDFs (one per claim)
- [ ] Aging report shows dollar amounts in 30/60/90/120+ buckets by carrier
- [ ] Auto-posting matches and posts ERA payments with ≥95% accuracy (same as match engine)
- [ ] Claim lifecycle tracks state transitions with timestamps
- [ ] All tests pass

### Notes for Lower-Level Models (Sonnet/Haiku)
```
IMPORTANT: When working on Sprint 14 tickets:
- Appeal letters must use Jinja2 templates, NOT f-strings with HTML.
  This prevents XSS. Always: render_template('appeal_letter.html', data=data)
- For scheduled reports (WF-03): use APScheduler or a simple cron-style loop.
  Don't use Celery — this is a local single-machine app.
- Aging report buckets: 0-30, 31-60, 61-90, 91-120, 120+.
  Calculate in SQL: CASE WHEN julianday('now') - julianday(service_date) <= 30 THEN '0-30' ...
- Auto-posting (WF-05) should reuse the existing match engine, not create a new one.
  Call run_matching() with auto_accept=0.95, then apply confirmed matches.
- For claim lifecycle (WF-06): use a state machine pattern.
  VALID_TRANSITIONS = {
      "SUBMITTED": ["PENDING", "DENIED"],
      "PENDING": ["PAID", "DENIED", "PARTIAL"],
      "DENIED": ["APPEALED", "WRITTEN_OFF"],
      "APPEALED": ["PAID", "PARTIAL", "WRITTEN_OFF"],
  }
  Reject invalid transitions instead of silently allowing them.
```

---

## Sprint 15: Production Polish

**Duration:** 1 week | **Goal:** Harden for daily production use
**This is the "make it bulletproof" sprint.**

### Tickets

| Ticket | Title | Priority | Est Hours | Depends On | Files |
|--------|-------|----------|-----------|------------|-------|
| PROD-01 | **Authentication: Flask-Login with local user accounts** | P0 | 8 | — | `app/__init__.py`, `app/models.py`, `app/auth/`, `templates/login.html` |
| PROD-02 | **Role-based access: admin vs viewer roles** | P1 | 4 | PROD-01 | `app/auth/decorators.py` |
| PROD-03 | **Error handlers: 404, 500 pages with useful messages** | P1 | 3 | — | `app/__init__.py`, `templates/404.html`, `templates/500.html` |
| PROD-04 | **Structured logging: JSON logs with request context** | P1 | 4 | — | `app/__init__.py`, `app/logging_config.py` |
| PROD-05 | **Health check endpoint enhancement: DB connectivity, disk space, backup age** | P2 | 3 | — | `app/ui/api.py` |
| PROD-06 | **Graceful startup: create all required directories, validate config** | P2 | 3 | — | `app/__init__.py` |
| PROD-07 | **Database backup improvements: scheduled auto-backup, retention policy** | P2 | 4 | — | `app/infra/backup_manager.py` |
| PROD-08 | **Rate limiting on upload endpoints** | P2 | 3 | — | `app/ui/api.py` |
| PROD-09 | **CORS configuration for local network access** | P3 | 2 | — | `app/__init__.py` |
| PROD-10 | **Deployment script: NSSM service wrapper with auto-restart** | P2 | 4 | — | `deploy/install_service.bat`, `deploy/README.md` |
| PROD-T01 | **Tests: auth, error handling, health checks** | P0 | 4 | all above | `tests/test_auth.py`, `tests/test_production.py` |

**Sprint 15 Total: 42 hours**

### Acceptance Criteria
- [ ] Login required for all pages; unauthenticated requests redirect to /login
- [ ] Admin role can modify payers, fee schedule, run imports; viewer role is read-only
- [ ] 404/500 pages render cleanly with navigation back to dashboard
- [ ] All requests logged with timestamp, endpoint, user, duration, status code
- [ ] Health endpoint reports: DB ok/error, disk free %, last backup age, record counts
- [ ] App starts cleanly even if uploads/, export/, backup/, schedule_data/ don't exist
- [ ] All tests pass

### Notes for Lower-Level Models (Sonnet/Haiku)
```
IMPORTANT: When working on Sprint 15 tickets:
- For auth (PROD-01): use Flask-Login with a User model.
  Hash passwords with werkzeug.security.generate_password_hash().
  NEVER store plaintext passwords.
  Create a default admin account on first run: admin/admin (force password change).
- For role-based access (PROD-02): use a simple decorator pattern.
  @login_required goes on every route.
  @admin_required goes on write/modify routes.
  Don't use a complex RBAC library — two roles is enough.
- For logging (PROD-04): use Python's built-in logging module.
  Log to both console and file (logs/ocdr.log).
  Use JSON format: {"timestamp": "...", "level": "INFO", "endpoint": "/api/dashboard/stats", ...}
- For error handlers (PROD-03): register with @app.errorhandler(404).
  Return HTML for browser requests, JSON for API requests (check Accept header).
- For health check (PROD-05): run a simple `SELECT 1` to verify DB.
  Check disk space with shutil.disk_usage('/').
  Check last backup file's mtime.
- NEVER disable or bypass authentication for convenience.
  Every endpoint must be protected. No exceptions.
```

---

## DEPENDENCY GRAPH

```
Sprint 11 (Schema)
    │
    ├──► Sprint 12 (Performance) ──► Sprint 14 (Workflows)
    │                                      │
    └──► Sprint 13 (LLM Layer) ───────────┘
                                           │
                                    Sprint 15 (Production)
```

Sprints 12 and 13 can run in parallel after Sprint 11.
Sprint 14 depends on both 12 and 13.
Sprint 15 is the final hardening sprint.

---

## TOTAL PHASE 2 EFFORT

| Sprint | Hours | Focus |
|--------|-------|-------|
| Sprint 11 | 73 | Schema hardening |
| Sprint 12 | 75 | Performance & safety |
| Sprint 13 | 86 | LLM integration |
| Sprint 14 | 74 | Advanced workflows |
| Sprint 15 | 42 | Production polish |
| **Total** | **350** | |

---

## SUCCESS METRICS (Phase 2)

| Metric | Current | After Phase 2 |
|--------|---------|---------------|
| Foreign key violations possible | Yes (0 FKs) | No (all enforced) |
| Dashboard load time (10K records) | 2-5 seconds | <500ms |
| Denial queue load time | Unbounded | <200ms |
| SQL injection risk | Low (parameterized) | Zero (whitelist + parameterized) |
| XSS vulnerabilities | 1 known | 0 |
| Authentication | None | Login required, role-based |
| LLM queryable | No | Yes (structured API + chat) |
| Appeal letter generation | Manual | Automated from templates |
| Backup strategy | Manual trigger | Auto-scheduled with retention |
| Migration system | None (db.create_all) | Alembic with up/down |
| Test count | 221 | 300+ |
