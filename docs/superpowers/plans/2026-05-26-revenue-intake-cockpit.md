# Revenue Intake Cockpit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a trialable `/import` cockpit that puts daily intake work, verification gates, portal downloads, and ScanSnap status on one dense screen.

**Architecture:** Keep existing backend endpoints and existing upload/import tools. Add a small frontend data-shaping helper for metrics/work items, then replace the Import page's first tab with a cockpit that consumes the helper and existing endpoint actions.

**Tech Stack:** React 18, react-bootstrap, existing `frontend/src/services/api`, Jest via `react-scripts test`, existing FastAPI endpoints.

---

## File Structure

- Create `frontend/src/pages/importCockpit.js` for pure helper functions: metrics, source rows, gate labels, and selected-item defaults.
- Create `frontend/src/pages/importCockpit.test.js` for red/green coverage of the helper.
- Modify `frontend/src/pages/Import.js` to render `RevenueIntakeCockpit` as the first tab and preserve existing manual import tabs.
- Modify `.gitignore` to ignore `.superpowers/` companion artifacts.

## Task 1: Cockpit Data Helper

**Files:**
- Create: `frontend/src/pages/importCockpit.js`
- Test: `frontend/src/pages/importCockpit.test.js`

- [ ] **Step 1: Write failing tests**

```javascript
import { buildCockpitModel, getInitialSelectedId } from "./importCockpit";

test("builds cockpit metrics and queue items from portal, scanner, and preview state", () => {
  const model = buildCockpitModel({
    portalStatus: {
      available: true,
      supported_count: 3,
      staged_count: 3,
      files: [
        { name: "oa-1.835", extension: ".835", supported: true, temporary: false, size: 1000 },
        { name: "ignore.tmp", extension: ".tmp", supported: false, temporary: true, size: 100 },
      ],
    },
    scannerStatus: {
      available: true,
      watcher_active: true,
      unclassified_count: 7,
      ocr_today_count: 43,
    },
    scanPreview: {
      total_files: 8,
      new_count: 2,
      already_processed_count: 6,
      new_files: [
        { path: "portal/2026-05-26/oa-1.835", extension: ".835", size_bytes: 1000 },
        { path: "scan/eob.pdf", extension: ".pdf", size_bytes: 2000 },
      ],
    },
  });

  expect(model.metrics.ready).toBe(5);
  expect(model.metrics.review).toBe(1);
  expect(model.metrics.blocked).toBe(0);
  expect(model.metrics.posted).toBe(6);
  expect(model.metrics.scannerQueue).toBe(7);
  expect(model.items.map((item) => item.id)).toEqual([
    "portal-staged",
    "scanner-queue",
    "scan-preview",
    "portal-file-oa-1.835",
  ]);
  expect(getInitialSelectedId(model.items)).toBe("portal-staged");
});

test("marks unavailable sources as blocked without inventing patient data", () => {
  const model = buildCockpitModel({
    portalStatus: { available: false, error: "missing staging folder", files: [] },
    scannerStatus: { available: false, error: "ssh failed" },
    scanPreview: null,
  });

  expect(model.metrics.blocked).toBe(2);
  expect(model.items).toHaveLength(2);
  expect(model.items.every((item) => item.status === "blocked")).toBe(true);
  expect(model.items.some((item) => item.patient)).toBe(false);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && npm test -- --runInBand --watchAll=false src/pages/importCockpit.test.js`

Expected: fail because `./importCockpit` does not exist.

- [ ] **Step 3: Implement helper**

Create `buildCockpitModel`, `getInitialSelectedId`, and helper functions that derive queue items from portal status, scanner status, and scan preview without PHI or fake patient rows.

- [ ] **Step 4: Run helper tests**

Run: `cd frontend && npm test -- --runInBand --watchAll=false src/pages/importCockpit.test.js`

Expected: all helper tests pass.

## Task 2: Import Page Cockpit

**Files:**
- Modify: `frontend/src/pages/Import.js`

- [ ] **Step 1: Add `RevenueIntakeCockpit`**

Use existing endpoint calls from `PortalDownloads`, `ScanSnapStatus`, and `EOBScanner`. Keep actions wired to:

- `GET /import/portal/status`
- `GET /import/portal/checklists`
- `POST /import/portal/promote?dry_run=true|false`
- `GET /import/scansnap/status`
- `GET /import/scan-eobs/preview`
- `POST /import/scan-eobs`

- [ ] **Step 2: Replace the first tab content**

Make `/import` open to `Revenue Cockpit`. The first tab should contain the KPI strip, queue table, evidence panel, and action rail. Keep Smart Import, Structured Excel, 835 ERA Import, and Import History as secondary tabs.

- [ ] **Step 3: Remove first-screen explainer cards**

Move explanation-heavy surfaces out of the first viewport. Use compact labels and status badges instead.

## Task 3: Verification

**Files:**
- Modify: `.gitignore`

- [ ] **Step 1: Ignore brainstorm artifacts**

Add `.superpowers/` to `.gitignore`.

- [ ] **Step 2: Run helper tests**

Run: `cd frontend && npm test -- --runInBand --watchAll=false src/pages/importCockpit.test.js`

Expected: all tests pass.

- [ ] **Step 3: Run frontend build**

Run: `cd frontend && npm run build`

Expected: build exits 0.

- [ ] **Step 4: Browser-check the cockpit**

Start the frontend app, open `/import`, and verify the first viewport shows the cockpit without relying on scrolling for the main workflow.
