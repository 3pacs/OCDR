# Portal Intake Bridge Design

## Scope

Connect the existing browser-assisted portal download lane to OCDR without changing the safety model for EOB posting. The bridge covers staged portal downloads, promoted import files, ScanSnap queue status, and per-payer download checklists.

## Architecture

The bridge is local-first. Chrome and payer auth stay in the operator's browser. Download collection stays in the existing host-side script. The backend only reads a configured staging directory, promotes supported files into the app's EOB import tree, exposes status endpoints, and reports ScanSnap queue counts when SSH to `ocr-node` is available.

Promotion is explicit and deduped by SHA-256. Files move from `OCDR_PORTAL_STAGING_DIR` into `EOBS_DIR/portal/YYYY-MM-DD/`; the existing `/api/import/scan-eobs` endpoint then imports that folder like any other EOB source. Canonical archive copy to `ocr-node:/mnt/topaz-mriserver/EOBS` stays manual/explicit until validation is hardened.

## Components

- `backend/app/ingestion/portal_downloads.py`: staged-file inventory, promotion, per-payer checklist data, and ScanSnap status helpers.
- `backend/app/api/routes/import_routes.py`: endpoints for portal status, promotion, checklists, and ScanSnap status.
- `frontend/src/pages/Import.js`: adds a Portal Downloads panel to the existing import screen.
- `docs/OCDR-PORTAL-DOWNLOADS.md`: documents the new bridge and operator flow.

## Compatibility

The backend must tolerate missing host-only paths. Docker deployments can bind-mount a staging folder or leave it missing; the endpoint returns a clear unavailable status instead of crashing. ScanSnap status is best-effort and returns unavailable when `ssh` is absent, blocked, or slow.

## Safety

No portal credentials are stored. The UI opens portal URLs in the browser and does not scrape sessions. No PHI is printed in chat or reports. Promotion manifests contain local filenames, sizes, hashes, and timestamps only.
