# Scheduling Pipeline Plan — Full-Day Machine Views + Three-Way Matching

## Overview

Build a full-day scheduling view per machine (MRI, PET) with an automated three-way matching pipeline: **Scanned PDFs → Candalis (Excel) → Purview (PACS)**. The system detects new files in watched folders, extracts all relevant data from PDFs, cross-references against Candalis billing data for provenance, then validates against Purview study records for consistency and error detection.

---

## What Exists Today

| Component | Status | Gaps |
|-----------|--------|------|
| `ScheduleRecord` model | Has patient_name, modality, date, time, referring_doctor, insurance_carrier, notes | Missing: co_pay_amount, co_pay_collected, candalis_match_id, purview_match_id, purview_accession, provenance_status |
| PDF schedule parser (`schedule_parser.py`) | Extracts names, dates, times, modality, scan type | Does NOT extract: insurance, referring doctor, co-pay, notes from PDF lines |
| Folder watcher (`folder_watcher.py`) | Routes .835/.csv/.xlsx/.txt files | Does NOT route .pdf files at all |
| Excel importer (`excel_importer.py`) | Imports billing records from Candalis spreadsheets | No concept of linking back to schedule records |
| Purview connector (`purview.py`) | Can log in and download exports | No study-level data matching or API-based lookup |
| Calendar view (`schedule_calendar.html`) | Monthly calendar with MRI vs PET/CT split | No full-day timeline view per machine |
| Schedule-to-billing matching | Exact patient_name + date match only | No fuzzy matching, no Candalis/Purview cross-reference |

---

## Implementation Steps

### Phase 1: Schema & Model Changes
**File: `app/models.py`**

Add new columns to `ScheduleRecord`:
- `co_pay_amount` — DECIMAL(10,2), nullable — co-pay amount from PDF
- `co_pay_collected` — Boolean, default False — whether co-pay was collected
- `candalis_record_id` — Integer FK to billing_records, nullable — matched Candalis row
- `candalis_match_status` — Text, default "PENDING" — PENDING / MATCHED / MISMATCH / NOT_FOUND
- `candalis_matched_at` — DateTime, nullable
- `purview_accession` — Text, nullable — Purview accession/study number
- `purview_match_status` — Text, default "PENDING" — PENDING / MATCHED / MISMATCH / NOT_FOUND
- `purview_matched_at` — DateTime, nullable
- `provenance_status` — Text, default "UNVERIFIED" — UNVERIFIED / PARTIAL / VERIFIED / ERROR
- `provenance_notes` — Text, nullable — discrepancy details

Add composite index: `(scheduled_date, modality, provenance_status)`

Update `to_dict()` to include all new fields.

Create manual ALTER TABLE migration script for existing databases.

### Phase 2: Enhanced PDF Parser
**File: `app/import_engine/schedule_parser.py`**

Enhance `parse_schedule_text()` to extract additional fields from each PDF line/block:

1. **Insurance extraction** — Add regex patterns for common insurance references:
   - `_INSURANCE_RE` matching: "INS:", "INSURANCE:", carrier names (MEDICARE, MEDI-CAL, CALOPTIMA, etc.), plan IDs
   - Map detected text through `validation.py:normalize_carrier()`

2. **Referring physician extraction** — Add regex:
   - `_DOCTOR_RE` matching: "DR.", "Dr.", "REF:", "REFERRING:", "MD", followed by name capture
   - Handle "ORDERED BY", "ORDERING PHYSICIAN" variants

3. **Co-pay extraction** — Add regex:
   - `_COPAY_RE` matching: "COPAY", "CO-PAY", "CP:", dollar amounts after co-pay keywords
   - Detect "COLLECTED", "PAID", "DUE" status markers

4. **Notes extraction** — Capture remaining text on the line after structured fields are parsed, or lines marked "NOTE:", "NOTES:", "COMMENT:"

5. Return enriched entry dict with: `insurance_carrier`, `referring_doctor`, `co_pay_amount`, `co_pay_collected`, `notes`

6. Update `_store_schedule_entries()` to populate all new fields on `ScheduleRecord`

### Phase 3: Folder Watcher PDF Routing
**File: `app/monitor/folder_watcher.py`**

1. Add `.pdf` to the extension routing in `_route_file()`:
   ```
   elif ext == ".pdf":
       return _process_pdf_schedule(filepath, filename)
   ```

2. Add `_process_pdf_schedule()` function:
   - Call `import_schedule_pdf(filepath)` from `schedule_parser.py`
   - Return standardized result dict with status/counts
   - After storing schedule records, trigger Phase 4 matching pipeline

3. Add configurable folder paths for schedule PDFs vs billing PDFs (so the watcher knows which PDFs are schedules vs ERA remittances). Options:
   - Subfolder convention: `uploads/import/schedules/` for schedule PDFs
   - Or filename pattern detection (schedule PDFs often have dates in the filename)

### Phase 4: Three-Way Matching Pipeline
**New file: `app/matching/schedule_reconciler.py`**

Build the automated three-way matching pipeline:

#### Step 1: PDF → Candalis (Excel) Matching
- After schedule records are imported from PDF, query `BillingRecord` for Candalis matches
- Match criteria (scored, not exact):
  - Patient name (fuzzy via rapidfuzz, reuse existing `match_engine.py` name scoring)
  - Service date = scheduled_date (±1 day tolerance)
  - Modality match
- On match: set `candalis_record_id`, `candalis_match_status = "MATCHED"`, `candalis_matched_at`
- On mismatch (partial match with discrepancies): set `candalis_match_status = "MISMATCH"`, log differences in `provenance_notes`
- On no match: set `candalis_match_status = "NOT_FOUND"`

#### Step 2: Candalis → Purview Validation
- For records with Candalis match, cross-reference against Purview data
- **Option A — File-based**: Parse Purview CSV/Excel exports (downloaded by existing `PurviewConnector`) to find matching studies by patient name + date + modality
- **Option B — API-based**: If Purview exposes a DICOM/WADO or REST API, query by accession number or patient ID (future enhancement)
- On match: set `purview_accession`, `purview_match_status = "MATCHED"`, `purview_matched_at`
- On mismatch: record discrepancy (e.g., different modality, date difference)
- Consistency checks:
  - Patient name matches across all three sources
  - Date matches across all three sources
  - Modality matches across all three sources
  - Flag any differences as `provenance_status = "ERROR"` with details

#### Step 3: Provenance Status Rollup
- `VERIFIED` — matched in all three systems (PDF + Candalis + Purview)
- `PARTIAL` — matched in two of three
- `UNVERIFIED` — only in one system
- `ERROR` — matched but with discrepancies

#### Trigger Points
- After PDF schedule import → run Step 1
- After Excel/CSV billing import → re-run Step 1 for unmatched schedules
- After Purview data download → run Step 2 for Candalis-matched records
- Manual trigger via API endpoint

### Phase 5: Candalis Data Source Identification
**File: `app/import_engine/excel_importer.py`**

1. Add `import_source` tagging: when an Excel file is imported, set `import_source = "CANDALIS"` on billing records (or make this configurable via the import UI / folder naming convention)
2. Add a `CANDALIS_FOLDER` config option in `app/config.py` for a dedicated Candalis import folder
3. The folder watcher routes files from `CANDALIS_FOLDER` to the Excel importer with the Candalis source tag

### Phase 6: Purview Data Import
**New file: `app/import_engine/purview_importer.py`**

1. Parse Purview export files (CSV/Excel) containing study-level data:
   - Patient name, accession number, study date, modality, study description
   - Referring physician, study status

2. Store in a new lightweight model or use a denormalized approach:
   - **Option A (recommended)**: Add a `PurviewStudy` model — id, patient_name, accession_number, study_date, modality, study_description, referring_physician, source_file, imported_at
   - **Option B**: Skip the model and do matching directly from the CSV/Excel in memory

3. Add `PURVIEW_FOLDER` config for dedicated Purview export folder
4. Route Purview exports through the folder watcher

### Phase 7: Full-Day Machine Schedule View
**New template: `templates/schedule_daily.html`**

Build a full-day timeline view showing one day's schedule per machine:

#### Layout
- Side-by-side columns: **MRI Machine** | **PET Machine**
- Vertical timeline from 6:00 AM to 8:00 PM (configurable)
- Each appointment is a block sized proportionally to its time slot (default 30-min blocks)
- Time slots along the left axis

#### Appointment Block Content
- Patient name (bold)
- Time slot (e.g., "9:00 AM - 9:30 AM")
- Scan type (e.g., "BRAIN MRI")
- Insurance carrier
- Referring physician
- Co-pay status (collected / due / N/A)
- Provenance badge: green check (VERIFIED), yellow warning (PARTIAL), red X (ERROR), gray (UNVERIFIED)

#### Color Coding
- Blue: Scheduled, verified
- Green: Completed
- Yellow/amber: Scheduled but provenance mismatch
- Red: Error — discrepancy between PDF/Candalis/Purview
- Gray: Cancelled / No-show

#### Navigation
- Date picker to jump to any day
- Previous/Next day arrows
- "Today" button
- Summary stats bar: total patients, verified count, mismatches, no-shows

#### API Endpoint
**File: `app/ui/api.py`**

Add `GET /api/schedule/daily?date=YYYY-MM-DD`:
- Returns two arrays: `mri_slots[]` and `pet_slots[]`
- Each slot: patient_name, scheduled_time, end_time (calculated from scan type duration or default 30 min), modality, scan_type, insurance_carrier, referring_doctor, co_pay_amount, co_pay_collected, provenance_status, provenance_notes, candalis_match_status, purview_match_status, status, notes
- Also returns day-level summary stats

### Phase 8: Auto-Import Integration
**File: `app/monitor/folder_watcher.py`**

Update the folder watcher to support the full pipeline:

1. **Watch multiple folders**:
   - `uploads/import/` — general import (existing)
   - `uploads/import/schedules/` — schedule PDFs (new)
   - `uploads/import/candalis/` — Candalis Excel files (new)
   - `uploads/import/purview/` — Purview exports (new)

2. **Pipeline orchestration after each import**:
   - PDF schedule imported → auto-trigger Candalis matching
   - Candalis data imported → auto-trigger re-match against unmatched schedules + Purview validation
   - Purview data imported → auto-trigger validation against Candalis-matched schedules

3. **Status dashboard updates**: emit import events that the daily view can poll for (existing refresh mechanism in the schedule page)

### Phase 9: API Endpoints for Reconciliation
**File: `app/ui/api.py`**

Add endpoints:
- `GET /api/schedule/reconciliation/summary` — counts by provenance_status
- `GET /api/schedule/reconciliation/mismatches` — list records with ERROR or MISMATCH status
- `POST /api/schedule/reconciliation/run` — manually trigger three-way matching for a date range
- `GET /api/schedule/reconciliation/detail/<id>` — full provenance chain for one record (PDF source → Candalis record → Purview study)

---

## File Change Summary

| File | Change Type | Description |
|------|-------------|-------------|
| `app/models.py` | MODIFY | Add columns to ScheduleRecord, add PurviewStudy model |
| `app/import_engine/schedule_parser.py` | MODIFY | Enhanced PDF extraction (insurance, doctor, co-pay, notes) |
| `app/monitor/folder_watcher.py` | MODIFY | Add PDF routing, multi-folder watching, pipeline triggers |
| `app/import_engine/excel_importer.py` | MODIFY | Add Candalis source tagging |
| `app/config.py` | MODIFY | Add CANDALIS_FOLDER, PURVIEW_FOLDER config |
| `app/matching/schedule_reconciler.py` | NEW | Three-way matching pipeline |
| `app/import_engine/purview_importer.py` | NEW | Purview export file parser |
| `templates/schedule_daily.html` | NEW | Full-day timeline view |
| `app/ui/api.py` | MODIFY | Add daily schedule + reconciliation endpoints |
| `app/ui/routes.py` | MODIFY | Add route for daily schedule page |
| `static/css/style.css` | MODIFY | Timeline/slot styling |
| `tests/test_schedule_reconciler.py` | NEW | Three-way matching tests |

---

## Implementation Order

1. **Phase 1** — Schema changes (model + migration)
2. **Phase 2** — Enhanced PDF parser (insurance, doctor, co-pay, notes)
3. **Phase 5** — Candalis source identification in Excel importer
4. **Phase 6** — Purview data import
5. **Phase 4** — Three-way matching pipeline (core logic)
6. **Phase 3** — Folder watcher PDF routing
7. **Phase 8** — Auto-import integration (multi-folder + pipeline triggers)
8. **Phase 7** — Full-day machine schedule view (UI)
9. **Phase 9** — Reconciliation API endpoints
10. Tests throughout

---

## Notes

- **Candalis is not currently in the codebase** — there's no reference to it. The Excel importer is generic. We need to identify which Excel files come from Candalis (by folder convention or filename pattern) and tag those records accordingly.
- **Purview connector exists** but only does browser-based login + file download. For study-level matching we need to parse the downloaded Purview exports (CSV/Excel) since there's no REST API integration yet.
- **The Anthropic API key** is available in config for AI-assisted import — this could be used to help with PDF field extraction when regex fails (structured extraction via Claude API).
- **No machine concept exists** — the system uses modality (HMRI, PET) as the machine proxy. If the imaging center has multiple machines of the same modality, we'd need a `machine_id` column, but for now MRI=one machine, PET=one machine is sufficient.
