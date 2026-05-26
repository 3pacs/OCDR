# Portal Intake Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect staged portal downloads to OCDR's EOB import lane, expose portal/ScanSnap status in the Import page, and add per-payer download checklists.

**Architecture:** Add a backend ingestion helper for staged-file inventory, SHA-256 deduped promotion, checklist data, and best-effort ScanSnap status. Expose those through import routes and render them in the existing React Import page. Keep Chrome auth, canonical archive copy, and PHI-heavy parsing out of the bridge.

**Tech Stack:** Python/FastAPI, pytest, React, react-bootstrap, existing `.env` settings.

---

### Task 1: Backend Portal Promotion Helper

**Files:**
- Create: `backend/app/ingestion/portal_downloads.py`
- Test: `backend/tests/test_portal_downloads.py`

- [ ] **Step 1: Write failing tests**

Cover staged inventory, dry-run promotion, real promotion, SHA-256 dedupe, checklist payload, and ScanSnap parser fallback.

- [ ] **Step 2: Verify tests fail**

Run: `python -m pytest backend/tests/test_portal_downloads.py -q`
Expected: import failure because `backend.app.ingestion.portal_downloads` does not exist.

- [ ] **Step 3: Implement helper**

Implement focused functions:
- `portal_status(staging_dir, state_dir, eobs_dir)`
- `promote_staged_downloads(staging_dir, state_dir, eobs_dir, dry_run=False, today=None)`
- `portal_checklists()`
- `scansnap_status(host="ocr-node", runner=None, today=None)`

- [ ] **Step 4: Verify helper tests pass**

Run: `python -m pytest backend/tests/test_portal_downloads.py -q`
Expected: all tests pass.

### Task 2: API Routes And Settings

**Files:**
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/api/routes/import_routes.py`
- Test: `backend/tests/test_portal_downloads.py`

- [ ] **Step 1: Add route-oriented tests**

Add tests for pure route payload helpers only if route extraction creates helpers; otherwise keep route behavior covered by helper tests.

- [ ] **Step 2: Add settings**

Add portal staging/state/import/archive and ScanSnap host settings with defaults compatible with local and Docker usage.

- [ ] **Step 3: Add endpoints**

Add:
- `GET /api/import/portal/status`
- `POST /api/import/portal/promote`
- `GET /api/import/portal/checklists`
- `GET /api/import/scansnap/status`

- [ ] **Step 4: Verify backend tests pass**

Run: `python -m pytest backend/tests/test_portal_download_collector.py backend/tests/test_portal_downloads.py -q`
Expected: all tests pass.

### Task 3: Import Page UI

**Files:**
- Modify: `frontend/src/pages/Import.js`

- [ ] **Step 1: Add Portal Downloads component**

Render portal checklists, status counts, staged/promoted file rows, promote dry-run, promote, scan-import promoted files, and refresh actions.

- [ ] **Step 2: Add ScanSnap Queue component**

Render watcher state, unclassified queue count, OCR output count, and unavailable/error state.

- [ ] **Step 3: Wire into existing Import page**

Place the new portal panel on the existing EOB Folder Scan tab so operators see portal files and folder scan together.

- [ ] **Step 4: Verify frontend build**

Run: `cd frontend; npm run build`
Expected: production build succeeds.

### Task 4: Docs And Final Verification

**Files:**
- Modify: `docs/OCDR-PORTAL-DOWNLOADS.md`
- Create: `C:\Users\anikd\Vault\00-Agent-Reports\2026-05-26\codex__ANIK__ocdr-portal-intake-bridge-2026-05-26.md`

- [ ] **Step 1: Update runbook**

Document status endpoint behavior, promote/scan flow, and archive handoff.

- [ ] **Step 2: Run verification**

Run:
- `python -m pytest backend/tests/test_portal_download_collector.py backend/tests/test_portal_downloads.py -q`
- `cd frontend; npm run build`

- [ ] **Step 3: Write PHI-safe report and sync vault**

Report paths, tests, counts, and follow-up items without patient details.
