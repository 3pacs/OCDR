"""
Schedule data importer.

Parses the structured CSV template that staff fill in after visually
inspecting the handwritten/scanned daily schedule.

The schedule is the ONLY source for:
  - Referring physician (until Purview lookup is automated)
  - Insurance carrier (at check-in)
  - Copay amount
  - OPEN MRI flag (noted for claustrophobic patients)

Data flow:
  1. Staff visually reads scanned schedule
  2. Fills in ``schedule_entry_template.csv``
  3. This module parses the CSV and produces OCMRI-compatible dicts
  4. Records are merged with Candelis data (matched by patient + date)
"""

import csv
from pathlib import Path
from decimal import Decimal
from typing import Optional

from ocdr import logger
from ocdr.normalizers import (
    normalize_patient_name, normalize_physician_name, normalize_payer_code,
    normalize_decimal, parse_date_flexible, derive_month, derive_year,
    normalize_modality,
)


def parse_schedule_file(filepath: str | Path) -> list[dict]:
    """Read a schedule entry CSV and return OCMRI-compatible dicts."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8", errors="replace")
    records = parse_schedule_csv(text, source_file=path.name)
    logger.log_import_summary(
        source=f"schedule:{path.name}",
        records_in=text.count("\n"),
        records_out=len(records),
        errors=[],
        warnings=[],
    )
    return records


def parse_schedule_csv(text: str, source_file: str = "") -> list[dict]:
    """Parse schedule entry CSV text.

    Expected columns (from template):
      patient_name, referring_doctor, insurance_carrier, copay,
      service_date, modality_override, notes

    Returns a list of dicts with normalized fields.
    """
    lines = text.strip().split("\n")
    if not lines:
        return []

    reader = csv.DictReader(lines)
    records: list[dict] = []
    errors: list[dict] = []

    for line_num, row in enumerate(reader, start=2):  # +2 for header + 1-indexed
        try:
            record = _parse_schedule_row(row, line_num)
            if record is not None:
                records.append(record)
        except Exception as e:
            errors.append({"line": line_num, "message": str(e)})
            logger.log_error(
                "schedule_parse_row",
                {"line": line_num, "row": dict(row)},
                e,
                suggested_fix="Check that the CSV matches the template format. "
                              "Verify column names match exactly.",
            )

    logger.log_import_summary(
        source=f"schedule_csv:{source_file}",
        records_in=len(lines) - 1,
        records_out=len(records),
        errors=errors,
        warnings=[],
    )
    return records


def _parse_schedule_row(row: dict, line_num: int) -> Optional[dict]:
    """Parse a single CSV row into an OCMRI-compatible dict."""
    raw_name = (row.get("patient_name") or "").strip()
    if not raw_name:
        return None

    patient_name = normalize_patient_name(raw_name)
    if not patient_name:
        return None

    referring_doctor = normalize_physician_name(row.get("referring_doctor"))
    insurance_carrier = normalize_payer_code(row.get("insurance_carrier"))
    copay = normalize_decimal(row.get("copay"))
    service_date = parse_date_flexible(row.get("service_date"))
    modality_override = normalize_modality(row.get("modality_override"))
    notes = (row.get("notes") or "").strip()

    # Review flags
    review_flags: list[str] = []
    if not service_date:
        review_flags.append("Missing service date — cannot match to Candelis")
    if not insurance_carrier:
        review_flags.append("Missing insurance carrier")
    if modality_override:
        review_flags.append(f"Schedule overrides modality to: {modality_override}")

    # Detect OPEN MRI from notes
    is_open_mri = False
    notes_upper = notes.upper()
    if "OPEN" in notes_upper or "CLAUSTROPHOB" in notes_upper:
        is_open_mri = True
        if not modality_override:
            modality_override = "OPEN"
        review_flags.append("OPEN MRI noted in schedule (claustrophobic patient)")

    logger.log_decision(
        "schedule_parse_row",
        {"line": line_num, "name": raw_name},
        {"patient_name": patient_name, "carrier": insurance_carrier,
         "modality_override": modality_override},
        flags=review_flags,
        confidence=1.0 if service_date else 0.5,
    )

    return {
        "patient_name": patient_name,
        "patient_name_display": patient_name,
        "referring_doctor": referring_doctor,
        "insurance_carrier": insurance_carrier,
        "extra_charges": copay,
        "service_date": service_date,
        "schedule_date": service_date,
        "service_month": derive_month(service_date),
        "service_year": derive_year(service_date),
        # Modality override from schedule (OPEN MRI detection)
        "modality_override": modality_override,
        "is_open_mri": is_open_mri,
        # Metadata
        "source": "SCHEDULE",
        "source_line": line_num,
        "notes": notes,
        "review_flags": review_flags,
    }


def merge_schedule_with_candelis(schedule_records: list[dict],
                                  candelis_records: list[dict]) -> list[dict]:
    """Merge schedule data into Candelis records by matching patient + date.

    The schedule provides: referring_doctor, insurance_carrier, copay,
    and OPEN MRI override.  Candelis provides: modality, scan_type,
    description, gado, etc.

    Matching is done on (patient_name, service_date).  When matched,
    the schedule fields are copied into the Candelis record.

    Returns the updated Candelis records list.  Unmatched schedule
    records are appended with a flag for review.
    """
    # Build schedule lookup: (patient_name, service_date) → record
    sched_lookup: dict[tuple, dict] = {}
    for sr in schedule_records:
        key = (sr.get("patient_name", ""), sr.get("service_date"))
        if key[0] and key[1]:
            sched_lookup[key] = sr

    merged: list[dict] = []
    matched_keys: set[tuple] = set()

    for cr in candelis_records:
        key = (cr.get("patient_name", ""), cr.get("service_date"))
        sched = sched_lookup.get(key)

        if sched:
            matched_keys.add(key)
            # Merge schedule fields into Candelis record
            cr["referring_doctor"] = sched.get("referring_doctor", "")
            cr["insurance_carrier"] = sched.get("insurance_carrier", "")
            cr["extra_charges"] = sched.get("extra_charges", Decimal("0.00"))

            # OPEN MRI override from schedule
            if sched.get("modality_override"):
                override = sched["modality_override"]
                if cr.get("modality") != override:
                    cr["review_flags"] = cr.get("review_flags", []) + [
                        f"Schedule overrides modality: {cr.get('modality')} → {override}"
                    ]
                cr["modality"] = override
                cr["suggested_modality"] = override
                cr["modality_confidence"] = 1.0
                cr["is_guess"] = False

            logger.log_decision(
                "schedule_merge",
                {"patient": key[0], "date": str(key[1])},
                {"merged_fields": ["referring_doctor", "insurance_carrier",
                                   "extra_charges", "modality_override"]},
                flags=[],
                reasoning=f"Matched schedule → Candelis for {key[0]} on {key[1]}",
            )
        else:
            # No schedule match — flag it
            if "No matching schedule entry" not in str(cr.get("review_flags", [])):
                cr.setdefault("review_flags", []).append(
                    "No matching schedule entry — referring doctor and insurance unknown"
                )

        merged.append(cr)

    # Append unmatched schedule records (patient on schedule but not in Candelis)
    for key, sr in sched_lookup.items():
        if key not in matched_keys:
            sr["review_flags"] = sr.get("review_flags", []) + [
                "Schedule entry has no matching Candelis study — "
                "patient may have cancelled or been rescheduled"
            ]
            merged.append(sr)
            logger.log_warning(
                "schedule_merge",
                f"Unmatched schedule entry: {key[0]} on {key[1]}",
                {"record": sr},
            )

    return merged
