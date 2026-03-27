"""Server file sync — autonomous polling of .NET server text files.

Scans a registered ServerSource directory for fixed-width text files,
detects new or modified files by comparing size/mtime against stored state,
parses them using the fixed-width parser, and upserts patient records.

This module is called by the background scheduler and can also be
triggered manually via the API.
"""

import logging
import os
from datetime import datetime
from pathlib import Path

from app.models import db, Patient, ServerSource
from app.parsing.fixed_width_parser import (
    looks_like_fixed_width,
    parse_fixed_width_records,
    _parse_date,
)

logger = logging.getLogger(__name__)

# File extensions to consider (extensionless files are also included)
_VALID_EXTENSIONS = {"", ".txt", ".dat", ".bin", ".raw", ".exp"}


def _should_process(filename: str) -> bool:
    """Check if a file should be processed as a fixed-width data file."""
    ext = Path(filename).suffix.lower()
    if ext not in _VALID_EXTENSIONS:
        return False
    base = Path(filename).stem.lower()
    skip_names = {"readme", "license", "changelog", "log", "error", "debug"}
    return base not in skip_names


def _file_changed(filepath: str, stored_state: dict | None) -> bool:
    """Check if a file has changed since last sync by comparing size and mtime."""
    if stored_state is None:
        return True
    try:
        stat = os.stat(filepath)
        return (
            stat.st_size != stored_state.get("size")
            or stat.st_mtime != stored_state.get("mtime")
        )
    except OSError:
        return False


def sync_server_source(source: ServerSource, force_full: bool = False) -> dict:
    """
    Sync a single server source — scan directory, parse new/modified files,
    upsert patient records.

    Args:
        source: The ServerSource configuration
        force_full: If True, re-process all files regardless of stored state

    Returns:
        dict with sync results (files_scanned, records_added, etc.)
    """
    directory = source.directory_path
    field_mapping = source.field_mapping or {}

    if not os.path.isdir(directory):
        source.status = "ERROR"
        source.last_error = f"Directory not found: {directory}"
        db.session.commit()
        return {"error": source.last_error}

    file_states = source.file_states or {} if not force_full else {}
    results = {
        "files_scanned": 0,
        "files_new": 0,
        "files_unchanged": 0,
        "files_errored": 0,
        "records_added": 0,
        "records_updated": 0,
        "errors": [],
    }

    try:
        entries = sorted(os.listdir(directory))
    except PermissionError:
        source.status = "ERROR"
        source.last_error = f"Permission denied: {directory}"
        db.session.commit()
        return {"error": source.last_error}

    # Load existing patients for upsert
    existing_patients = Patient.query.all()
    patient_index: dict[tuple, Patient] = {}
    for p in existing_patients:
        patient_index[(p.jacket_number, p.topaz_number)] = p

    new_file_states = dict(file_states)

    for entry in entries:
        filepath = os.path.join(directory, entry)
        if not os.path.isfile(filepath):
            continue
        if not _should_process(entry):
            continue

        results["files_scanned"] += 1

        stored = file_states.get(entry)
        if not _file_changed(filepath, stored):
            results["files_unchanged"] += 1
            continue

        try:
            with open(filepath, "rb") as f:
                content_bytes = f.read()
        except (OSError, PermissionError) as e:
            results["files_errored"] += 1
            results["errors"].append(f"{entry}: {e}")
            continue

        try:
            content_str = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            content_str = content_bytes.decode("latin-1", errors="replace")
        content_bytes_clean = content_str.replace("\x00", "").encode("utf-8")

        if not looks_like_fixed_width(content_bytes_clean):
            stat = os.stat(filepath)
            new_file_states[entry] = {
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "records": 0,
                "skipped": True,
            }
            continue

        try:
            fw_result = parse_fixed_width_records(content_bytes_clean)
        except Exception as e:
            results["files_errored"] += 1
            results["errors"].append(f"{entry}: Parse error: {e}")
            continue

        if fw_result.total_records == 0:
            continue

        results["files_new"] += 1

        added, updated = _upsert_patients_from_records(
            fw_result, field_mapping, source.id, entry, patient_index
        )
        results["records_added"] += added
        results["records_updated"] += updated

        stat = os.stat(filepath)
        new_file_states[entry] = {
            "size": stat.st_size,
            "mtime": stat.st_mtime,
            "records": fw_result.total_records,
        }

    # Update source record
    source.file_states = new_file_states
    source.last_sync_at = datetime.utcnow()
    source.last_sync_result = results
    source.total_files_processed = sum(
        1 for s in new_file_states.values() if not s.get("skipped")
    )
    source.total_records_imported += results["records_added"]
    source.status = "ACTIVE"
    source.last_error = None
    db.session.commit()

    logger.info(
        f"Server sync '{source.name}': "
        f"{results['files_scanned']} files scanned, "
        f"{results['files_new']} new, "
        f"{results['records_added']} records added, "
        f"{results['records_updated']} updated"
    )

    return results


def _upsert_patients_from_records(
    fw_result,
    field_mapping: dict,
    source_id: int,
    filename: str,
    patient_index: dict[tuple, Patient],
) -> tuple[int, int]:
    """
    Extract patient data from parsed fixed-width records and upsert
    into the patients table.

    Returns (added_count, updated_count).
    """
    added = 0
    updated = 0

    chart_field = field_mapping.get("chart_number")
    topaz_field = field_mapping.get("topaz_id")
    use_line_as_topaz = topaz_field == "_line_num"
    last_name_field = field_mapping.get("last_name")
    first_name_field = field_mapping.get("first_name")
    name_field = field_mapping.get("patient_name")

    for rec in fw_result.records:
        # Extract identifiers
        jacket = None
        if chart_field:
            val = rec.get(chart_field, "").strip()
            if val:
                try:
                    jacket = str(int(float(val)))
                except (ValueError, TypeError):
                    jacket = val

        topaz = None
        if use_line_as_topaz:
            topaz = str(rec.get("_line_num", ""))
        elif topaz_field:
            val = rec.get(topaz_field, "").strip()
            topaz = val if val else None

        if not jacket and not topaz:
            continue

        # Extract names
        last_name = None
        first_name = None
        if last_name_field:
            last_name = rec.get(last_name_field, "").strip() or None
        if first_name_field:
            first_name = rec.get(first_name_field, "").strip() or None
        if not last_name and name_field:
            full = rec.get(name_field, "").strip()
            if full:
                if "," in full:
                    parts = full.split(",", 1)
                    last_name = parts[0].strip()
                    first_name = parts[1].strip() if len(parts) > 1 else None
                elif " " in full:
                    parts = full.split(None, 1)
                    last_name = parts[0].strip()
                    first_name = parts[1].strip() if len(parts) > 1 else None
                else:
                    last_name = full

        # Extract DOB
        dob = None
        dob_field = field_mapping.get("date_of_birth")
        if dob_field:
            dob_str = rec.get(dob_field, "").strip()
            if dob_str:
                parsed = _parse_date(dob_str)
                if parsed:
                    from datetime import date as date_cls
                    try:
                        dob = date_cls.fromisoformat(parsed)
                    except ValueError:
                        pass

        # Extract other fields
        phone = _extract_field(rec, field_mapping, "phone")
        city = _extract_field(rec, field_mapping, "city")
        state = _extract_field(rec, field_mapping, "state")
        zip_code = _extract_field(rec, field_mapping, "zip_code")
        insurance_number = _extract_field(rec, field_mapping, "insurance_number")

        # Upsert
        key = (jacket, topaz)
        existing = patient_index.get(key)

        if existing:
            changed = False
            for attr, val in [
                ("last_name", last_name),
                ("first_name", first_name),
                ("date_of_birth", dob),
                ("phone", phone),
                ("city", city),
                ("state", state),
                ("zip_code", zip_code),
                ("insurance_number", insurance_number),
            ]:
                if val and not getattr(existing, attr):
                    setattr(existing, attr, val)
                    changed = True
            if changed:
                updated += 1
        else:
            patient = Patient(
                jacket_number=jacket,
                topaz_number=topaz,
                last_name=last_name,
                first_name=first_name,
                date_of_birth=dob,
                phone=phone,
                city=city,
                state=state,
                zip_code=zip_code,
                insurance_number=insurance_number,
            )
            db.session.add(patient)
            patient_index[key] = patient
            added += 1

    return added, updated


def _extract_field(rec: dict, field_mapping: dict, role: str) -> str | None:
    """Extract a simple string field from a record using the field mapping."""
    src = field_mapping.get(role)
    if not src:
        return None
    val = rec.get(src, "").strip()
    return val if val else None


def sync_all_sources() -> list[dict]:
    """Sync all enabled server sources. Called by the background scheduler."""
    sources = ServerSource.query.filter(
        ServerSource.enabled.is_(True),
        ServerSource.status.in_(["ACTIVE", "PENDING_SETUP"]),
    ).all()

    all_results = []
    for source in sources:
        try:
            sync_result = sync_server_source(source)
            all_results.append({
                "source_id": source.id,
                "name": source.name,
                "result": sync_result,
            })
        except Exception as e:
            logger.error(f"Error syncing source '{source.name}': {e}")
            source.status = "ERROR"
            source.last_error = str(e)
            db.session.commit()
            all_results.append({
                "source_id": source.id,
                "name": source.name,
                "error": str(e),
            })

    return all_results
