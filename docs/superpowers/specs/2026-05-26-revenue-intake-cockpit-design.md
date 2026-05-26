# Revenue Intake Cockpit Design

## Goal

Redesign the OCDR import experience around the revenue lifecycle: get the patient and remittance data ingested, billed correctly, payment collected, payment logged, and enough granular status captured to optimize the process later.

## Approved Direction

Use a dense Work Queue Cockpit as the first screen on `/import`.

The cockpit replaces the current scan-first card layout with a single operational screen:

- Top KPI strip for ready, review, blocked, posted/imported, and scanner queue counts.
- Left work queue for portal downloads, ScanSnap/OCR queue, EOB archive/import work, and current scan/import results.
- Middle evidence panel for the selected work item, including source, payer/file, amount, lifecycle stage, verification gates, and recent events.
- Right action rail for the next operator actions: preview/promote portal downloads, scan import folder, open payer portals, open review/import surfaces, and view ScanSnap status.

## UX Principles

- Speed and correctness beat completeness on every pass.
- Avoid scrolling as the primary workflow. The first viewport must answer "what should I do next?"
- Use compact tables, badges, and action groups instead of long explanatory cards.
- Center work items and dual-verification state, not portals or tools.
- Show only the checks that matter for the current item. Exception rows get human attention; verified rows should flow quickly.
- Keep manual upload/import tools available, but secondary to the daily work queue.

## Data Sources For First Pass

The first pass uses existing local endpoints and state:

- `GET /api/import/portal/status`
- `GET /api/import/portal/checklists`
- `POST /api/import/portal/promote?dry_run=true|false`
- `GET /api/import/scansnap/status`
- `GET /api/import/scan-eobs/preview`
- `POST /api/import/scan-eobs`

This first pass is file/source-oriented because the full patient lifecycle queue does not exist yet. It still uses lifecycle language and verification gates so the later backend queue can slot in without changing the operator model.

## Verification Gates

Rows expose a compact gate status:

- `ready`: source is present and ready for the next automated action.
- `review`: human review is needed before import/posting.
- `blocked`: action cannot continue until a source, date, identity, or parser issue is resolved.
- `posted`: work was imported/logged and is no longer a daily action item.

The UI must not imply that final posting is safe unless the backend has performed the workbook/Topaz/payment-source verification required by OCMRI rules.

## First-Pass Scope

Build the cockpit inside the existing Import page. Preserve the existing Smart Import, Structured Excel, 835 upload, and Import History tabs as compact secondary tabs.

Do not build a fake patient queue. Until a lifecycle API exists, work items are derived from portal staging, ScanSnap queue status, and scan preview/import results.

## Out Of Scope

- Browser automation for payer portal downloads.
- Automatic workbook writes from the cockpit.
- Patient-level lifecycle API design.
- Bank deposit matching UI.
- New authentication/storage flows.

## Testing

Add tests for the frontend data-shaping helpers that convert portal/scanner/preview state into cockpit metrics and work queue items. Verify the React build after implementation.
