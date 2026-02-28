# OCDR Bug Tracker

Issues found during comprehensive testing and code audit. All 156 existing tests pass.

---

## CRITICAL

### Issue #1: XSS Vulnerability in Physician Statement HTML Generation
- **File:** `app/revenue/physician_statements.py:138-174`
- **Description:** `generate_statement_html()` renders user-supplied data (physician names, patient names, carrier names) directly into HTML using f-strings without escaping. An attacker could inject arbitrary JavaScript via malicious patient/physician names.
- **Impact:** Stored XSS — any user viewing a generated statement could execute attacker-controlled JavaScript in their browser.
- **Reproduction:**
  ```python
  data = {'physician_name': '<script>alert(document.cookie)</script>', ...}
  html = generate_statement_html(data)  # script tag rendered verbatim
  ```
- **Fix:** Use `markupsafe.escape()` or Jinja2 templating with auto-escaping on all user-supplied values before inserting into HTML.

### Issue #2: No Authentication or Authorization on Any API Endpoint
- **File:** `app/ui/api.py` (all endpoints), `app/__init__.py`
- **Description:** Every API endpoint is completely unauthenticated. No login, no session tokens, no API keys. The `/api/denials/<id>/resolve` endpoint can modify payment data, `/api/admin/payers` can modify payer configs, and `/api/import/*` can insert arbitrary data — all without any auth.
- **Impact:** Anyone with network access can read all patient billing data, modify financial records, import malicious data, or delete backups. For a healthcare billing system, this is a HIPAA compliance violation.
- **Fix:** Add authentication middleware (Flask-Login, JWT, or OAuth). At minimum, add API key authentication for all write endpoints.

---

## HIGH

### Issue #3: Denial Queue Loads ALL Records Into Memory (No DB-Level Pagination)
- **File:** `app/revenue/denial_tracker.py:32`
- **Description:** `get_denial_queue()` calls `query.all()` to load every denied record into Python memory, computes recoverability scores in a loop, sorts in Python, then slices for pagination. This is an O(N) memory and O(N*M) query operation where M = FeeSchedule lookups per record.
- **Impact:** With thousands of denied claims, this will cause severe memory usage and slow response times. Could OOM the server.
- **Fix:** Compute recoverability in SQL using a join with fee_schedule, use `ORDER BY` and `LIMIT/OFFSET` for server-side pagination.

### Issue #4: N+1 Query in Denial Queue (FeeSchedule + EraClaimLine per Record)
- **File:** `app/revenue/denial_tracker.py:37-49`, `app/revenue/denial_tracker.py:120-128`
- **Description:** For each denied billing record, `_recoverability_score()` executes a separate `FeeSchedule.query.filter_by()` (up to 2 queries per record). Additionally, for each record with `era_claim_id`, a separate `EraClaimLine.query.filter_by()` is issued. With 1000 denials, this is 2000-3000 individual queries.
- **Impact:** Extremely slow API response. Database connection exhaustion under load.
- **Fix:** Pre-load FeeSchedule into a dict, batch-load EraClaimLines by claim_ids.

### Issue #5: Filing Deadlines Loads ALL Unpaid Records Into Memory
- **File:** `app/ui/api.py:195`
- **Description:** `/api/filing-deadlines` calls `.all()` on all unpaid billing records, iterates through them in Python to compute deadline status. No pagination on the data fetch.
- **Impact:** Memory spike on large datasets. The endpoint caps output at 200 items but still loads everything.
- **Fix:** Compute deadline status in SQL, paginate at the database level.

### Issue #6: Underpayment Summary Loads ALL Paid Records
- **File:** `app/ui/api.py:1478`
- **Description:** `_get_underpayment_summary()` loads every paid billing record via `.all()` and iterates in Python to check each against the fee schedule. This is called from `/api/dashboard/stats` (the main dashboard) meaning every dashboard load triggers a full-table scan.
- **Impact:** Dashboard loads will be slow with large datasets, consuming excessive memory.
- **Fix:** Perform the underpayment calculation in SQL with a JOIN against fee_schedule.

### Issue #7: N+1 Query in Match Results
- **File:** `app/matching/match_engine.py:284`
- **Description:** `get_match_results()` does `BillingRecord.query.get(claim.matched_billing_id)` inside a loop for each matched claim. This is a classic N+1 query pattern.
- **Impact:** Slow responses when viewing match results with many matched claims.
- **Fix:** Collect all `matched_billing_id` values and batch-load with `BillingRecord.query.filter(BillingRecord.id.in_(ids)).all()`.

### Issue #8: Match Engine O(N*M) Query Pattern
- **File:** `app/matching/match_engine.py:186-226`
- **Description:** `run_matching()` loads ALL unmatched claims, then for EACH claim issues a separate database query to find billing candidates within the date window. For 5000 unmatched claims, this is 5000 separate queries.
- **Impact:** Matching will be very slow for large datasets.
- **Fix:** Pre-load billing records grouped by date, or use a single query with a self-join approach.

### Issue #9: `confirm_match` Allows Setting Non-Existent billing_id
- **File:** `app/matching/match_engine.py:230-245`
- **Description:** `confirm_match(claim_id, billing_id)` sets `matched_billing_id` to any integer without validating that the billing record exists. There's no foreign key constraint on the column either.
- **Impact:** Data integrity — matched_billing_id can reference non-existent records, causing errors downstream when trying to look up the billing record.
- **Fix:** Validate that `BillingRecord.query.get(billing_id)` exists before setting. Add FK constraint.

### Issue #10: LIKE Wildcard Characters Not Escaped in User Input
- **File:** `app/ui/api.py:796,835,837`, `app/revenue/physician_statements.py:31,38,95`
- **Description:** User input is inserted directly into ILIKE patterns as `f"%{user_input}%"`. While SQLAlchemy parameterizes this (preventing SQL injection), the `%` and `_` characters in user input act as LIKE wildcards, allowing broader matching than intended.
- **Impact:** A user searching for "%" would match all records. Low severity but unintended behavior.
- **Fix:** Escape `%` and `_` in user input before using in ILIKE patterns.

---

## MEDIUM

### Issue #11: Thread Safety Issues in Folder Monitor
- **File:** `app/monitor/folder_watcher.py:15-17, 169-186`
- **Description:** Global variables `_monitor_running`, `_monitor_status`, and `_monitor_thread` are shared between threads without any locking. `start_monitor()` has a TOCTOU race: it checks `_monitor_running` then sets it, allowing two threads to start simultaneously.
- **Impact:** Potential double-processing of files, corrupted status dict, or race conditions if start/stop called concurrently.
- **Fix:** Use `threading.Lock()` to protect shared state. Use an `Event` for the running flag.

### Issue #12: Monitor Error List Grows Unbounded (Memory Leak)
- **File:** `app/monitor/folder_watcher.py:17, 144, 147`
- **Description:** `_monitor_status["errors"]` is a list that gets `.append()` called on every error but is never truncated. Over time with continuous monitoring, this list grows indefinitely.
- **Impact:** Memory leak proportional to error count over the lifetime of the process.
- **Fix:** Cap the errors list (e.g., keep last 100 errors) or use a deque with maxlen.

### Issue #13: `resolve_denial` Creates Payment Data Inconsistency
- **File:** `app/revenue/denial_tracker.py:94-105`
- **Description:** When resolving a denial with a payment amount, the code sets both `total_payment` and `primary_payment` to the same value, but doesn't touch `secondary_payment`. If the record previously had a secondary payment, `total_payment != primary_payment + secondary_payment`.
- **Impact:** Financial data inconsistency — reported totals won't add up correctly.
- **Fix:** Either set `secondary_payment = 0` when resolving, or set `total_payment = payment_amount + record.secondary_payment`.

### Issue #14: Deprecated SQLAlchemy `Query.get()` Usage
- **Files:** `app/revenue/denial_tracker.py:86,96,112`, `app/matching/match_engine.py:236,250,284`, `app/revenue/physician_statements.py:121`
- **Description:** Multiple files use `Model.query.get(id)` which is deprecated in SQLAlchemy 2.0. The code emits `LegacyAPIWarning` on every call.
- **Impact:** Will break when upgrading to SQLAlchemy 2.0+. Currently produces warning noise.
- **Fix:** Replace with `db.session.get(Model, id)`.

### Issue #15: `EraPayment.to_dict()` Triggers Lazy Load N+1
- **File:** `app/models.py:82`
- **Description:** `EraPayment.to_dict()` accesses `self.claim_lines` which triggers a lazy load query. When listing payments (e.g., `/api/era/payments`), each payment triggers a separate query for its claim lines just to get the count.
- **Impact:** N+1 query on payment listing endpoints.
- **Fix:** Use `db.session.query(func.count(...))` for the count, or use `lazy="dynamic"` / `lazy="select"` with a dedicated count property.

### Issue #16: CSV Export Loads ALL Records Into Memory
- **File:** `app/export/csv_exporter.py:72`
- **Description:** `export_billing_csv()` calls `.all()` on the entire billing_records table. With a large dataset, this loads everything into memory at once.
- **Impact:** Memory exhaustion for large datasets during export.
- **Fix:** Use `.yield_per(1000)` or streaming/chunked export.

### Issue #17: Hardcoded Default Secret Key
- **File:** `app/config.py:7`
- **Description:** `SECRET_KEY` defaults to `"ocdr-dev-key-change-in-production"` if the environment variable isn't set. In production, if this isn't overridden, Flask session cookies can be forged.
- **Impact:** Session forgery in production if SECRET_KEY not set via environment.
- **Fix:** Raise an error if SECRET_KEY is not set in production, or generate a random key.

### Issue #18: 835 Parser `parse_835_file` Uses `rsplit` for Path Handling
- **File:** `app/parser/era_835_parser.py:316`
- **Description:** `filename = filepath.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]` is a fragile cross-platform path handling approach instead of using `os.path.basename()`.
- **Impact:** Could produce wrong filename on edge cases (e.g., paths with mixed separators).
- **Fix:** Use `os.path.basename(filepath)`.

---

## LOW

### Issue #19: `datetime.utcnow()` Used Throughout (Deprecated in Python 3.12+)
- **Files:** `app/models.py:31,68,181`, `app/export/csv_exporter.py:88`, `app/monitor/folder_watcher.py:154`
- **Description:** `datetime.utcnow()` is deprecated in Python 3.12+. Should use `datetime.now(timezone.utc)` instead.
- **Impact:** Will emit deprecation warnings on Python 3.12+, eventually removed.
- **Fix:** Replace with `datetime.now(datetime.timezone.utc)`.

### Issue #20: Missing `per_page` Bounds Validation on Pagination Parameters
- **File:** `app/ui/api.py` (multiple endpoints)
- **Description:** `per_page` accepts any integer from query params. A request with `per_page=1000000` would attempt to load a million records.
- **Impact:** Potential DoS via large page size.
- **Fix:** Cap `per_page` to a reasonable maximum (e.g., 500).

### Issue #21: Folder Watcher `shutil.move` Can Overwrite Existing Files
- **File:** `app/monitor/folder_watcher.py:138-139,143,149-150`
- **Description:** When moving processed/errored files, `shutil.move()` will silently overwrite if a file with the same name already exists in the destination folder.
- **Impact:** Could lose error files or processed file references.
- **Fix:** Add timestamp suffix to destination filename or check existence first.

### Issue #22: No File Extension Validation on Upload Endpoints
- **File:** `app/ui/api.py:650-784` (ERA upload), `app/ui/api.py:921-992` (import endpoints)
- **Description:** Upload endpoints accept any file regardless of extension. While `secure_filename()` is used, there's no validation that the uploaded file actually matches the expected type (e.g., someone could upload an executable to the Excel import endpoint).
- **Impact:** Low risk since files are processed by specific parsers, but wastes resources on invalid files.
- **Fix:** Validate file extension before saving.

### Issue #23: Bank Statement Import Has No File Size Limit
- **File:** `app/core/payment_matching.py:58-107`
- **Description:** `import_bank_statement()` reads the entire CSV into memory without any row limit. While MAX_CONTENT_LENGTH limits upload size, a 100MB CSV could still have millions of rows.
- **Impact:** Memory exhaustion on very large bank statements.
- **Fix:** Add a row count limit or process in chunks.
