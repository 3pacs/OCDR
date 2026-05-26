# OCDR portal downloads

This is the browser-assisted EOB/ERA download lane for the broader OCDR workflow.

## Why it works this way

Portal auth stays in Chrome. OCDR does not read saved passwords, scrape Chrome credential storage, or run a headless Office Ally login. This avoids the Office Ally timeout/lockout behavior already noted in the codebase while still giving the agent a repeatable way to collect files after you download them.

## Config

Local values live in `.env`:

- `OCDR_PORTAL_URLS`: Office Ally reset/login, Optum Pay, and One Healthcare ID portal URLs.
- `OCDR_PORTAL_DOWNLOAD_DIR`: Chrome download folder.
- `OCDR_PORTAL_STAGING_DIR`: PHI-local staging folder for newly downloaded files.
- `OCDR_PORTAL_STATE_DIR`: local manifest folder used for SHA-256 dedupe.
- `OCDR_PORTAL_DOWNLOAD_EXTENSIONS`: file types to collect.
- `OCDR_PORTAL_MIN_AGE_SECONDS`: wait time before collecting a newly modified file.
- `OCDR_PORTAL_MAX_AGE_HOURS`: recent-download window to scan by default.
- `OCDR_OFFICEALLY_RESET_DELAY_SECONDS`: delay between the Office Ally logout/reset URL and login URL.

`.env` is gitignored. Do not commit downloaded portal files or manifests that contain local file names.

## Manual-auth download loop

Open the portals in Chrome:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\open_portal_downloads.ps1
```

Office Ally opens as a two-step reset: first `https://www.officeally.com/Logout.aspx?Timeout=1`, then `https://x02.officeally.com/auth0bridge/Logon?ReturnUrl=/secure_oa.asp`.

Download EOB, ERA, 835, or remittance files from the portal screens. When downloads finish, stage the new files:

```powershell
python scripts\collect_portal_downloads.py
```

Preview without copying:

```powershell
python scripts\collect_portal_downloads.py --dry-run --json
```

By default, the collector only scans files modified in the last 72 hours so it does not hash an entire old Downloads folder. Use `--all` for a full backfill.

The collector copies supported files into `OCDR_PORTAL_STAGING_DIR`, dedupes by SHA-256 across runs, and writes only metadata to `OCDR_PORTAL_STATE_DIR\manifest.json`.

## OCDR import handoff

The Import page includes a Portal Downloads panel:

- `Refresh` reads `OCDR_PORTAL_STAGING_DIR`.
- `Preview Promote` dry-runs copying supported staged files into `EOBS_DIR\portal\YYYY-MM-DD`.
- `Promote to Import Folder` copies new files into the OCDR import tree and records SHA-256 promotions in `OCDR_PORTAL_STATE_DIR\promotions.json`.
- `Scan Import Folder` runs the existing EOB folder scanner against `EOBS_DIR`.

The same flow is available from the API:

```powershell
curl http://localhost:8000/api/import/portal/status
curl -X POST "http://localhost:8000/api/import/portal/promote?dry_run=true"
curl -X POST "http://localhost:8000/api/import/portal/promote?dry_run=false"
curl -X POST http://localhost:8000/api/import/scan-eobs
```

Docker note: if the backend runs in Docker, the Windows staging folder is not visible unless it is bind-mounted into the container. Without a mount, the status endpoint returns an unavailable state instead of crashing. For pure Docker use, point `OCDR_PORTAL_STAGING_DIR` at a mounted path such as `/app/data/portal-staging`.

## ScanSnap status

The Import page also has a ScanSnap Queue panel backed by:

```powershell
curl http://localhost:8000/api/import/scansnap/status
```

It checks `ocr-node` by SSH for the ScanSnap watcher, `_unclassified` queue count, and today's OCR output count. If SSH is unavailable, the panel reports unavailable without blocking portal imports.

## Archive handoff

After staging, review/promote files into the active EOB archive or OCDR import folder for the specific workflow being run. Current Obsidian notes say the active machine-readable EOB archive is:

```text
ocr-node:/mnt/topaz-mriserver/EOBS
```

Keep promotion explicit until the per-payer download and validation rules are hardened.
