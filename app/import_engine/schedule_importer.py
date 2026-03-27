"""Schedule data importer — reads CSV and Excel files from a configurable folder.

Supports column mappings for common scheduling export formats:
  patient_name, scan_type, modality, scheduled_date, scheduled_time,
  referring_doctor, insurance_carrier, location, status, notes

Files are moved to a 'processed/' subfolder after successful import.
"""

import csv
import os
import shutil
from datetime import datetime

from app.models import db, ScheduleRecord


# Column name aliases (lowercase) mapped to model fields
COLUMN_MAP = {
    "patient_name": "patient_name",
    "patient": "patient_name",
    "name": "patient_name",
    "scan_type": "scan_type",
    "scan": "scan_type",
    "exam": "scan_type",
    "exam_type": "scan_type",
    "procedure": "scan_type",
    "modality": "modality",
    "mod": "modality",
    "type": "modality",
    "scheduled_date": "scheduled_date",
    "date": "scheduled_date",
    "appt_date": "scheduled_date",
    "appointment_date": "scheduled_date",
    "scheduled_time": "scheduled_time",
    "time": "scheduled_time",
    "appt_time": "scheduled_time",
    "referring_doctor": "referring_doctor",
    "doctor": "referring_doctor",
    "physician": "referring_doctor",
    "ref_doctor": "referring_doctor",
    "referring_physician": "referring_doctor",
    "insurance_carrier": "insurance_carrier",
    "insurance": "insurance_carrier",
    "carrier": "insurance_carrier",
    "payer": "insurance_carrier",
    "location": "location",
    "facility": "location",
    "site": "location",
    "status": "status",
    "appt_status": "status",
    "notes": "notes",
    "comments": "notes",
}

VALID_MODALITIES = {"HMRI", "CT", "PET", "OPEN", "BONE", "DX", "GH"}

DATE_FORMATS = [
    "%Y-%m-%d",
    "%m/%d/%Y",
    "%m/%d/%y",
    "%m-%d-%Y",
    "%Y/%m/%d",
    "%d-%b-%Y",
    "%b %d, %Y",
]


def _parse_date(val):
    """Try multiple date formats."""
    if not val:
        return None
    val = val.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def _normalize_modality(val):
    """Map common modality names to standard codes."""
    if not val:
        return None
    val = val.strip().upper()
    aliases = {
        "MRI": "HMRI",
        "HMRI": "HMRI",
        "CT": "CT",
        "CAT": "CT",
        "PET": "PET",
        "PET/CT": "PET",
        "PETCT": "PET",
        "BONE": "BONE",
        "OPEN": "OPEN",
        "OPEN MRI": "OPEN",
        "DX": "DX",
        "X-RAY": "DX",
        "XRAY": "DX",
        "GH": "GH",
    }
    return aliases.get(val, val)


def _resolve_columns(headers):
    """Map file headers to model field names."""
    mapping = {}
    for i, h in enumerate(headers):
        key = h.strip().lower().replace(" ", "_")
        if key in COLUMN_MAP:
            mapping[i] = COLUMN_MAP[key]
    return mapping


def import_csv(filepath):
    """Import a single CSV file. Returns (imported_count, errors)."""
    filename = os.path.basename(filepath)
    records = []
    errors = []
    skipped_dupes = 0
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader, None)
        if not headers:
            return 0, ["Empty file or no headers"]

        col_map = _resolve_columns(headers)
        if "patient_name" not in col_map.values() or "scheduled_date" not in col_map.values():
            return 0, [f"Missing required columns (patient_name, scheduled_date). Found: {headers}"]

        for row_num, row in enumerate(reader, start=2):
            try:
                data = {}
                for idx, field in col_map.items():
                    if idx < len(row):
                        data[field] = row[idx].strip()

                patient_name = data.get("patient_name", "UNKNOWN").upper()
                sched_date = _parse_date(data.get("scheduled_date", ""))
                if not sched_date:
                    errors.append(f"Row {row_num}: invalid date '{data.get('scheduled_date', '')}'")
                    continue

                modality = _normalize_modality(data.get("modality", ""))
                if not modality:
                    errors.append(f"Row {row_num}: missing modality")
                    continue

                # Dedup: skip if same patient+date already exists
                existing = ScheduleRecord.query.filter_by(
                    patient_name=patient_name,
                    scheduled_date=sched_date,
                ).first()
                if existing:
                    skipped_dupes += 1
                    continue

                records.append(ScheduleRecord(
                    patient_name=patient_name,
                    scan_type=data.get("scan_type", data.get("modality", "")),
                    modality=modality,
                    scheduled_date=sched_date,
                    scheduled_time=data.get("scheduled_time"),
                    referring_doctor=data.get("referring_doctor"),
                    insurance_carrier=data.get("insurance_carrier"),
                    location=data.get("location"),
                    status=data.get("status", "SCHEDULED").upper(),
                    notes=data.get("notes"),
                    source_file=filename,
                    import_source="FOLDER_IMPORT",
                ))
            except Exception as e:
                errors.append(f"Row {row_num}: {str(e)}")

    if records:
        db.session.bulk_save_objects(records)
        db.session.commit()

    return len(records), errors


def import_excel(filepath):
    """Import a single Excel file. Returns (imported_count, errors)."""
    try:
        import openpyxl
    except ImportError:
        return 0, ["openpyxl not installed"]

    filename = os.path.basename(filepath)
    records = []
    errors = []

    wb = openpyxl.load_workbook(filepath, read_only=True, data_only=True)
    ws = wb.active

    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        return 0, ["Empty spreadsheet"]

    headers = [str(h or "").strip() for h in rows[0]]
    col_map = _resolve_columns(headers)

    if "patient_name" not in col_map.values() or "scheduled_date" not in col_map.values():
        return 0, [f"Missing required columns. Found: {headers}"]

    for row_num, row in enumerate(rows[1:], start=2):
        try:
            data = {}
            for idx, field in col_map.items():
                if idx < len(row):
                    val = row[idx]
                    data[field] = str(val).strip() if val is not None else ""

            patient_name = data.get("patient_name", "UNKNOWN").upper()
            raw_date = data.get("scheduled_date", "")
            # openpyxl may return datetime objects directly
            if isinstance(row[next(i for i, f in col_map.items() if f == "scheduled_date")], datetime):
                sched_date = row[next(i for i, f in col_map.items() if f == "scheduled_date")].date()
            else:
                sched_date = _parse_date(raw_date)

            if not sched_date:
                errors.append(f"Row {row_num}: invalid date '{raw_date}'")
                continue

            modality = _normalize_modality(data.get("modality", ""))
            if not modality:
                errors.append(f"Row {row_num}: missing modality")
                continue

            # Dedup: skip if same patient+date already exists
            existing = ScheduleRecord.query.filter_by(
                patient_name=patient_name,
                scheduled_date=sched_date,
            ).first()
            if existing:
                continue

            records.append(ScheduleRecord(
                patient_name=patient_name,
                scan_type=data.get("scan_type", data.get("modality", "")),
                modality=modality,
                scheduled_date=sched_date,
                scheduled_time=data.get("scheduled_time"),
                referring_doctor=data.get("referring_doctor"),
                insurance_carrier=data.get("insurance_carrier"),
                location=data.get("location"),
                status=data.get("status", "SCHEDULED").upper(),
                notes=data.get("notes"),
                source_file=filename,
                import_source="FOLDER_IMPORT",
            ))
        except Exception as e:
            errors.append(f"Row {row_num}: {str(e)}")

    wb.close()

    if records:
        db.session.bulk_save_objects(records)
        db.session.commit()

    return len(records), errors


def import_folder(folder_path):
    """Scan a folder for CSV/Excel schedule files, import them, move to processed/.

    Returns dict with summary of results per file.
    """
    if not os.path.isdir(folder_path):
        return {"error": f"Folder not found: {folder_path}"}

    processed_dir = os.path.join(folder_path, "processed")
    os.makedirs(processed_dir, exist_ok=True)

    results = {}
    for filename in sorted(os.listdir(folder_path)):
        filepath = os.path.join(folder_path, filename)
        if not os.path.isfile(filepath):
            continue

        ext = os.path.splitext(filename)[1].lower()
        if ext == ".csv":
            count, errors = import_csv(filepath)
        elif ext in (".xlsx", ".xls"):
            count, errors = import_excel(filepath)
        else:
            continue

        results[filename] = {"imported": count, "errors": errors}

        # Move to processed folder
        dest = os.path.join(processed_dir, filename)
        if os.path.exists(dest):
            base, fext = os.path.splitext(filename)
            dest = os.path.join(processed_dir, f"{base}_{datetime.now().strftime('%Y%m%d%H%M%S')}{fext}")
        shutil.move(filepath, dest)

    return results
