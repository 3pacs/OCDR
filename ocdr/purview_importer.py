"""
Purview RIS physician merger.

Purview is currently used ONLY for looking up referring physician names.
This is done visually (staff reads Purview and types the name).

This module provides:
  1. A physician reference table (CSV) that accumulates over time
  2. Merge logic to auto-populate referring_doctor on billing records
  3. Fuzzy matching for name variants

Over time, the reference table grows and reduces manual lookups.

Data flow:
  1. Staff enters physician names from Purview into reference CSV
  2. ``load_physician_reference()`` reads the CSV
  3. ``merge_physicians()`` fills in referring_doctor on records
  4. ``save_physician_reference()`` persists new discoveries
"""

import csv
from pathlib import Path
from difflib import SequenceMatcher
from typing import Optional

from ocdr import logger
from ocdr.normalizers import normalize_patient_name, normalize_physician_name


def load_physician_reference(filepath: str | Path) -> dict[str, str]:
    """Load a physician reference CSV mapping patient_name → referring_doctor.

    CSV format::

        patient_name,referring_doctor
        "TORRES, JULIA","DR. SMITH"
        "PATINO, MARGARET","DR. JONES"

    Returns a dict mapping normalized patient names to physician names.
    """
    path = Path(filepath)
    if not path.exists():
        logger.log_warning(
            "purview_load",
            f"Physician reference file not found: {path}",
            {"path": str(path)},
        )
        return {}

    mapping: dict[str, str] = {}
    errors: list[dict] = []

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)
        for line_num, row in enumerate(reader, start=2):
            try:
                raw_patient = (row.get("patient_name") or "").strip()
                raw_doctor = (row.get("referring_doctor") or "").strip()
                if raw_patient and raw_doctor:
                    patient = normalize_patient_name(raw_patient)
                    doctor = normalize_physician_name(raw_doctor)
                    if patient:
                        mapping[patient] = doctor
            except Exception as e:
                errors.append({"line": line_num, "error": str(e)})
                logger.log_error(
                    "purview_load_row",
                    {"line": line_num, "row": dict(row)},
                    e,
                    suggested_fix="Check CSV format: patient_name,referring_doctor",
                )

    logger.log_import_summary(
        source=f"purview:{path.name}",
        records_in=line_num if 'line_num' in dir() else 0,
        records_out=len(mapping),
        errors=errors,
        warnings=[],
    )
    return mapping


def save_physician_reference(filepath: str | Path,
                              mapping: dict[str, str]) -> None:
    """Save the physician reference table to CSV."""
    path = Path(filepath)
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["patient_name", "referring_doctor"])
        writer.writeheader()
        for patient, doctor in sorted(mapping.items()):
            writer.writerow({"patient_name": patient, "referring_doctor": doctor})

    logger.log_decision(
        "purview_save",
        {"path": str(path)},
        {"entries": len(mapping)},
        flags=[],
        reasoning=f"Saved {len(mapping)} physician reference entries.",
    )


def merge_physicians(records: list[dict],
                      physician_map: dict[str, str]) -> list[dict]:
    """Fill in referring_doctor on records that are missing it.

    Uses exact name match first, then fuzzy match (>= 90% similarity).
    Returns the updated records list (mutated in-place).
    """
    filled = 0
    fuzzy_filled = 0

    for r in records:
        if r.get("referring_doctor"):
            continue  # Already has a doctor — don't overwrite

        patient = r.get("patient_name", "")
        if not patient:
            continue

        # Exact match
        if patient in physician_map:
            r["referring_doctor"] = physician_map[patient]
            filled += 1
            continue

        # Fuzzy match
        best_match, best_score = _fuzzy_find(patient, physician_map)
        if best_match and best_score >= 0.90:
            r["referring_doctor"] = physician_map[best_match]
            r.setdefault("review_flags", []).append(
                f"Physician auto-filled via fuzzy match "
                f"({best_score:.0%}): '{patient}' ≈ '{best_match}'"
            )
            fuzzy_filled += 1
            logger.log_decision(
                "purview_fuzzy_match",
                {"patient": patient, "matched_to": best_match},
                {"doctor": physician_map[best_match], "similarity": best_score},
                flags=["fuzzy_match"],
                confidence=best_score,
                reasoning=f"Fuzzy matched '{patient}' → '{best_match}' "
                          f"({best_score:.0%}) for physician lookup.",
            )

    logger.log_decision(
        "purview_merge_summary",
        {"total_records": len(records)},
        {"exact_filled": filled, "fuzzy_filled": fuzzy_filled},
        flags=[],
        reasoning=f"Filled {filled} exact + {fuzzy_filled} fuzzy physician matches.",
    )
    return records


def discover_new_physicians(records: list[dict],
                             existing_map: dict[str, str]) -> dict[str, str]:
    """Extract new patient→doctor associations from records.

    Returns only NEW entries (not already in existing_map).
    These can be reviewed and added to the reference table.
    """
    new_entries: dict[str, str] = {}
    for r in records:
        patient = r.get("patient_name", "")
        doctor = r.get("referring_doctor", "")
        if patient and doctor and patient not in existing_map:
            new_entries[patient] = doctor
    return new_entries


def _fuzzy_find(name: str,
                mapping: dict[str, str]) -> tuple[Optional[str], float]:
    """Find the best fuzzy match for a name in the physician map."""
    best_key = None
    best_score = 0.0

    for key in mapping:
        score = SequenceMatcher(None, name.upper(), key.upper()).ratio()
        if score > best_score:
            best_score = score
            best_key = key

    return best_key, best_score
