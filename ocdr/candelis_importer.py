"""
Candelis PACS data importer.

Parses the tab-separated text that staff copy/paste from the Candelis
web GUI.  The paste is saved as a ``.txt`` file and fed to this module.

Data flow:
  1. Split raw text into rows/columns (tab-separated)
  2. Normalise names (remove ``^`` marks, format as ``LAST, FIRST``)
  3. Fill continuation rows (blank patient = additional study for previous
     patient)
  4. Map description → suggested modality + scan type (with confidence)
  5. Expand C.A.P line items based on insurance type
  6. Output list of dicts ready for the staging workbook

RESEARCH entries are **kept** — their names are normalised, not filtered.
"""

from pathlib import Path
from decimal import Decimal
from typing import Optional

from ocdr import logger
from ocdr.normalizers import (
    normalize_patient_name, parse_date_flexible, date_to_excel_serial,
    derive_month, derive_year, map_candelis_modality, detect_gado_from_desc,
    detect_psma, extract_scan_type,
)
from ocdr.business_rules import expand_cap_line_items, check_insurance_caveats


# ── Column indices in the tab-separated paste ──────────────────────────────
# Based on the real sample data provided by the user.
COL_STATUS      = 0
COL_PATIENT_ID  = 1
COL_BIRTH_DATE  = 2
COL_PATIENT_NAME = 3
COL_STUDY_DATE  = 4
COL_MODALITIES  = 5   # Machine/equipment codes (MR, SR/CT, CT/SR/PT/SC, DX)
COL_DESCRIPTION = 6   # Actual procedure (the PRIMARY modality indicator)
COL_NUM_SERIES  = 7
COL_NUM_INST    = 8
COL_AE_TITLE    = 9   # AE_MRI or RESEARCH
COL_ST          = 10
MIN_COLUMNS     = 7    # Minimum columns for a parseable row


def parse_candelis_file(filepath: str | Path) -> list[dict]:
    """Read a saved Candelis paste from a text file."""
    path = Path(filepath)
    text = path.read_text(encoding="utf-8", errors="replace")
    records = parse_candelis_paste(text)
    logger.log_import_summary(
        source=f"candelis:{path.name}",
        records_in=text.count("\n"),
        records_out=len(records),
        errors=[],
        warnings=[],
    )
    return records


def parse_candelis_paste(text: str) -> list[dict]:
    """Parse raw tab-separated Candelis paste text.

    Returns a list of OCMRI-compatible dicts.  Each dict includes:
      - Standard billing fields (patient_name, service_date, etc.)
      - ``suggested_modality`` and ``modality_confidence``
      - ``review_flags`` list of issues requiring human review
      - ``is_research`` bool
    """
    lines = text.strip().split("\n")
    records: list[dict] = []
    errors: list[dict] = []
    prev_patient: Optional[dict] = None  # for continuation rows

    for line_num, line in enumerate(lines, start=1):
        line = line.strip()
        if not line:
            continue

        cols = line.split("\t")
        if len(cols) < MIN_COLUMNS:
            errors.append({
                "line": line_num,
                "message": f"Too few columns ({len(cols)}), expected >= {MIN_COLUMNS}",
                "raw": line[:200],
            })
            logger.log_warning("candelis_parse", f"Line {line_num}: too few columns", {"cols": len(cols)})
            continue

        try:
            record = _parse_row(cols, line_num, prev_patient)
            if record is not None:
                records.append(record)
                # Update prev_patient for continuation row support
                if record.get("patient_name"):
                    prev_patient = {
                        "patient_name": record["patient_name"],
                        "patient_id": record.get("patient_id"),
                        "birth_date": record.get("birth_date"),
                    }
        except Exception as e:
            errors.append({"line": line_num, "message": str(e)})
            logger.log_error(
                "candelis_parse_row",
                {"line": line_num, "raw": line[:200]},
                e,
                suggested_fix="Check if the Candelis paste format has changed. "
                              "Verify tab separation and column order.",
            )

    # Expand C.A.P records into multiple line items
    expanded: list[dict] = []
    for r in records:
        desc = r.get("description", "").upper()
        if "C.A.P" in desc or "CAP" in desc.replace(".", ""):
            items = expand_cap_line_items(r, is_research=r.get("is_research", False))
            expanded.extend(items)
        else:
            expanded.append(r)

    logger.log_import_summary(
        source="candelis_paste",
        records_in=len(lines),
        records_out=len(expanded),
        errors=errors,
        warnings=[],
    )
    return expanded


def _parse_row(cols: list[str], line_num: int,
               prev_patient: Optional[dict]) -> Optional[dict]:
    """Parse a single tab-separated row into a billing record dict."""

    # ── Extract raw values ──
    raw_status = _col(cols, COL_STATUS)
    raw_pid    = _col(cols, COL_PATIENT_ID)
    raw_dob    = _col(cols, COL_BIRTH_DATE)
    raw_name   = _col(cols, COL_PATIENT_NAME)
    raw_date   = _col(cols, COL_STUDY_DATE)
    raw_mods   = _col(cols, COL_MODALITIES)
    raw_desc   = _col(cols, COL_DESCRIPTION)
    raw_ae     = _col(cols, COL_AE_TITLE)

    # ── Handle continuation rows ──
    # When patient ID and name are both blank, this is an additional study
    # for the previous patient.  Copy their info forward.
    is_continuation = (not raw_pid and not raw_name)
    if is_continuation and prev_patient:
        patient_name = prev_patient["patient_name"]
        patient_id = prev_patient.get("patient_id")
        birth_date = prev_patient.get("birth_date")
        logger.log_decision(
            "continuation_row",
            {"line": line_num, "raw_desc": raw_desc},
            {"patient_name": patient_name},
            flags=["continuation"],
            reasoning=f"Line {line_num} has no patient — using previous: {patient_name}",
        )
    elif is_continuation and prev_patient is None:
        # First row is a continuation row with no previous patient
        logger.log_warning("candelis_parse", f"Line {line_num}: continuation row but no previous patient", {})
        return None
    else:
        patient_name = normalize_patient_name(raw_name)
        patient_id = int(raw_pid) if raw_pid and raw_pid.isdigit() else None
        birth_date = parse_date_flexible(raw_dob)

    if not patient_name:
        return None

    # ── Parse dates ──
    service_date = parse_date_flexible(raw_date)

    # ── Determine if RESEARCH ──
    is_research = (raw_ae or "").strip().upper() == "RESEARCH"

    # ── Map modality (description-first, machine verifies) ──
    suggested_modality, modality_confidence = map_candelis_modality(raw_mods, raw_desc)

    # ── Extract scan type from description ──
    scan_type = extract_scan_type(raw_desc)

    # ── Detect gado and PSMA ──
    gado = detect_gado_from_desc(raw_desc)
    psma = detect_psma(raw_desc)

    # ── Build review flags ──
    review_flags: list[str] = []
    if modality_confidence < 1.0:
        review_flags.append(
            f"Modality uncertain ({modality_confidence:.0%}): "
            f"suggested '{suggested_modality}' from desc='{raw_desc}' machine='{raw_mods}'"
        )
    if modality_confidence == 0.0:
        review_flags.append("MODALITY UNKNOWN — must be manually classified")
    if is_continuation:
        review_flags.append("Continuation row (patient copied from previous)")
    if is_research:
        review_flags.append("RESEARCH study — separate C.A.P billing rules apply")

    # Run insurance caveats (best-guess + flag)
    # (Insurance carrier is blank from Candelis — will be filled from schedule)
    # But if this is RESEARCH, flag it
    if is_research:
        review_flags.append("RESEARCH: verify billing modality matches research protocol")

    # ── Log the decision ──
    logger.log_decision(
        "candelis_map_record",
        {"line": line_num, "name": raw_name, "desc": raw_desc, "mods": raw_mods},
        {"modality": suggested_modality, "confidence": modality_confidence,
         "scan_type": scan_type, "gado": gado},
        flags=review_flags,
        confidence=modality_confidence,
    )

    return {
        # Core patient fields
        "patient_name": patient_name,
        "patient_id": patient_id,
        "birth_date": birth_date,
        # Service info
        "service_date": service_date,
        "schedule_date": service_date,  # same for Candelis
        # Modality (suggested — staff makes final call)
        "suggested_modality": suggested_modality,
        "modality": suggested_modality,  # best guess
        "modality_confidence": modality_confidence,
        "modality_code": (raw_mods or "").strip().upper(),
        # Scan details
        "scan_type": scan_type,
        "description": (raw_desc or "").strip(),
        "gado_used": gado,
        "is_psma": psma,
        # Derived
        "service_month": derive_month(service_date),
        "service_year": derive_year(service_date),
        # Metadata
        "is_research": is_research,
        "ae_title": (raw_ae or "").strip().upper(),
        "source": "CANDELIS",
        "source_line": line_num,
        "review_flags": review_flags,
        "is_guess": modality_confidence < 1.0,
        # Fields to be filled later (from schedule, Purview, EOBs)
        "referring_doctor": "",
        "insurance_carrier": "",
        "primary_payment": Decimal("0.00"),
        "secondary_payment": Decimal("0.00"),
        "total_payment": Decimal("0.00"),
        "extra_charges": Decimal("0.00"),
        "reading_physician": "",
        "patient_name_display": patient_name,
        "is_new_patient": False,
    }


def _col(cols: list[str], idx: int) -> str:
    """Safely get a column value, returning empty string if out of range."""
    if idx < len(cols):
        return cols[idx].strip()
    return ""
