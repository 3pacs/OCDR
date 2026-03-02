"""
Business rules BR-01 through BR-11 from BUILD_SPEC.

Every rule is a pure function operating on lists of dicts (billing records)
or individual records.  No side-effects, no I/O.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Dict, Tuple, Optional
from collections import defaultdict
from difflib import SequenceMatcher

from ocdr.config import get_expected_rate, get_payer, UNDERPAYMENT_THRESHOLD


# ── BR-01  C.A.P Exception ────────────────────────────────────────────────

def detect_cap_exceptions(records: list[dict]) -> list[dict]:
    """Mark records that are part of a C.A.P triple (same patient + date,
    with CHEST + ABDOMEN + PELVIS) so they are NOT flagged as duplicates.

    Mutates ``record["is_cap_exception"]`` in-place and returns the list.
    """
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("service_date"):
            groups[(r["patient_name"], r["service_date"])].append(r)

    cap_parts = {"CHEST", "ABDOMEN", "PELVIS"}

    for _key, group in groups.items():
        descs = {r.get("description", "").upper().replace(".", "") for r in group}
        scans = {r.get("scan_type", "") for r in group}
        has_cap_desc = any("CAP" in d for d in descs)
        has_cap_parts = cap_parts.issubset(scans)

        if has_cap_desc or (has_cap_parts and len(group) >= 3):
            for r in group:
                if r.get("scan_type", "") in cap_parts:
                    r["is_cap_exception"] = True
    return records


# ── BR-02  PSMA Detection ─────────────────────────────────────────────────

def detect_psma_flags(records: list[dict]) -> list[dict]:
    """Set ``is_psma=True`` when description contains PSMA / Ga-68 / gallium."""
    kw = ("PSMA", "GA-68", "GALLIUM")
    for r in records:
        d = r.get("description", "").upper()
        if any(k in d for k in kw):
            r["is_psma"] = True
    return records


# ── BR-04  Missing Secondary ──────────────────────────────────────────────

def detect_missing_secondary(records: list[dict]) -> list[dict]:
    """Return records where payer expects secondary but none was paid."""
    results = []
    for r in records:
        payer = get_payer(r.get("insurance_carrier", ""))
        if (payer["has_secondary"]
                and r.get("primary_payment", Decimal("0")) > 0
                and r.get("secondary_payment", Decimal("0")) == 0):
            results.append(r)
    return results


# ── BR-05  Timely Filing Deadline ─────────────────────────────────────────

def detect_filing_issues(records: list[dict],
                         as_of: date | None = None
                         ) -> Tuple[list[dict], list[dict]]:
    """Return ``(past_deadline, warning_30day)`` lists of unpaid records."""
    if as_of is None:
        as_of = date.today()

    past, warning = [], []
    for r in records:
        if r.get("total_payment", Decimal("0")) > 0:
            continue
        sd = r.get("service_date")
        if sd is None:
            continue
        days = get_payer(r.get("insurance_carrier", ""))["deadline"]
        deadline = sd + timedelta(days=days)
        warn_date = deadline - timedelta(days=30)
        r["filing_deadline"] = deadline
        r["filing_days_remaining"] = (deadline - as_of).days
        if as_of > deadline:
            r["filing_status"] = "PAST_DEADLINE"
            past.append(r)
        elif as_of > warn_date:
            r["filing_status"] = "WARNING_30DAY"
            warning.append(r)
        else:
            r["filing_status"] = "SAFE"
    return past, warning


# ── BR-08  Denial Recoverability Score ────────────────────────────────────

def recoverability_score(billed: Decimal, service_date: date,
                         as_of: date | None = None) -> float:
    """``billed * (1 - days_old / 365)``  — higher = more worth pursuing."""
    if as_of is None:
        as_of = date.today()
    days = max((as_of - service_date).days, 0)
    return float(billed) * max(0.0, 1.0 - days / 365.0)


# ── BR-09  Cross-Reference Match Score ────────────────────────────────────
#
# All fields must agree for 100 % confidence.  Any single mismatch
# reduces the score and flags the record for human review.

def compute_match_score(billing: dict, era_claim: dict) -> dict:
    """Composite matching score with per-field breakdown.

    Returns a dict::

        {
            "score":      float 0-1,
            "name_sim":   float 0-1,
            "date_match": float 0-1,
            "modality_match": float 0-1,
            "body_part_match": float 0-1,
            "mismatches": [str, …],   # human-readable list of problems
        }

    All four sub-scores must be 1.0 for the overall score to be 1.0.
    """
    mismatches: list[str] = []

    # ── Name similarity (SequenceMatcher) ──
    bn = billing.get("patient_name", "").upper()
    en = era_claim.get("patient_name", "").upper()
    name_sim = SequenceMatcher(None, bn, en).ratio() if bn and en else 0.0
    if name_sim < 0.85:
        mismatches.append(f"Name mismatch: '{bn}' vs '{en}' ({name_sim:.0%})")

    # ── Date match ──
    bd = billing.get("service_date")
    ed = era_claim.get("service_date")
    if bd and ed:
        diff = abs((bd - ed).days)
        date_match = {0: 1.0, 1: 0.8, 2: 0.5}.get(diff, 0.0)
    else:
        date_match = 0.0
    if date_match < 1.0:
        mismatches.append(f"Date mismatch: {bd} vs {ed}")

    # ── Modality match ──
    bm = billing.get("modality", "")
    em = era_claim.get("modality", "")
    modality_match = 1.0 if bm and em and bm == em else 0.0
    if modality_match < 1.0:
        mismatches.append(f"Modality mismatch: '{bm}' vs '{em}'")

    # ── Body part / scan type match ──
    bs = billing.get("scan_type", "")
    es = era_claim.get("scan_type", "")
    if bs and es:
        body_sim = SequenceMatcher(None, bs, es).ratio()
        body_match = 1.0 if body_sim >= 0.8 else body_sim
    else:
        body_match = 0.0  # missing data → can't confirm
    if body_match < 1.0:
        mismatches.append(f"Body part mismatch: '{bs}' vs '{es}'")

    # ── Composite: ALL must be 1.0 for 100 % ──
    # Weighted so any single failure pulls score well below auto-accept
    score = (0.35 * name_sim
             + 0.25 * date_match
             + 0.20 * modality_match
             + 0.20 * body_match)

    return {
        "score": round(score, 4),
        "name_sim": round(name_sim, 4),
        "date_match": round(date_match, 4),
        "modality_match": round(modality_match, 4),
        "body_part_match": round(body_match, 4),
        "mismatches": mismatches,
    }


# ── BR-11  Underpayment Detection ─────────────────────────────────────────

def detect_underpayments(records: list[dict]) -> list[dict]:
    """Return dicts enriched with expected_rate / variance for underpaid claims."""
    flagged = []
    for r in records:
        total = r.get("total_payment", Decimal("0"))
        if total <= 0:
            continue
        expected = get_expected_rate(
            r.get("modality", ""),
            r.get("insurance_carrier", "DEFAULT"),
            r.get("is_psma", False),
            r.get("gado_used", False),
        )
        if expected <= 0:
            continue
        pct = total / expected
        if pct < UNDERPAYMENT_THRESHOLD:
            flagged.append({
                **r,
                "expected_rate": expected,
                "variance": total - expected,
                "pct_of_expected": round(float(pct), 4),
            })
    return flagged


# ── Duplicate Detection (uses BR-01 exclusion) ────────────────────────────

def detect_duplicates(records: list[dict]) -> list[list[dict]]:
    """Groups of 2+ records sharing patient+date+scan+modality.
    Excludes C.A.P exceptions (BR-01)."""
    records = detect_cap_exceptions(records)
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in records:
        if r.get("is_cap_exception"):
            continue
        key = (r.get("patient_name"), r.get("service_date"),
               r.get("scan_type"), r.get("modality"))
        groups[key].append(r)
    return [g for g in groups.values() if len(g) > 1]


# ── Denial Detection ──────────────────────────────────────────────────────

def detect_denials(records: list[dict]) -> list[dict]:
    """Records with total_payment == 0."""
    return [r for r in records if r.get("total_payment", Decimal("0")) == 0]


# ── C.A.P Line-Item Expansion ─────────────────────────────────────────────
#
# C.A.P (Chest/Abdomen/Pelvis) billing varies by insurer:
#   RESEARCH → 3 separate line items (CHEST, ABDOMEN, PELVIS)
#   All others → 2 line items (CHEST, A/P combined)
#
# This is config-driven so new payer-specific rules can be added.

# Payers that get 3 separate C.A.P line items
CAP_THREE_ITEM_PAYERS = {"RESEARCH"}

def expand_cap_line_items(record: dict,
                          is_research: bool = False) -> list[dict]:
    """Expand a C.A.P record into the correct number of billing rows.

    Args:
        record: A single billing record whose description contains C.A.P.
        is_research: True if this study comes from a RESEARCH AE Title
                     or a payer in CAP_THREE_ITEM_PAYERS.

    Returns:
        List of 2 or 3 billing record dicts, one per line item.
        Each is a copy of the original with ``scan_type`` set to the
        specific body part.
    """
    desc = record.get("description", "").upper()
    if "C.A.P" not in desc.replace(" ", "") and "CAP" not in desc.replace(".", ""):
        # Not a C.A.P record — return as-is
        return [record]

    carrier = record.get("insurance_carrier", "")
    three_items = is_research or carrier in CAP_THREE_ITEM_PAYERS

    base = dict(record)  # shallow copy
    base["is_cap_exception"] = True
    base["cap_expansion"] = True

    if three_items:
        # RESEARCH: 3 separate items
        rows = []
        for part in ("CHEST", "ABDOMEN", "PELVIS"):
            r = dict(base)
            r["scan_type"] = part
            r["cap_item"] = f"{part} (3-item RESEARCH)"
            rows.append(r)
        return rows
    else:
        # Standard: 2 items — CHEST + A/P
        r1 = dict(base)
        r1["scan_type"] = "CHEST"
        r1["cap_item"] = "CHEST (2-item standard)"
        r2 = dict(base)
        r2["scan_type"] = "A/P"
        r2["cap_item"] = "A/P (2-item standard)"
        return [r1, r2]


# ── Insurance Caveats (extensible) ─────────────────────────────────────────
#
# Each caveat is a function that takes a record and returns a list of
# flags/warnings.  New caveats are added here as they are discovered.

def check_insurance_caveats(record: dict) -> list[str]:
    """Run all known insurance-specific caveats against a record.

    Returns a list of human-readable flag strings.  Empty = no issues.
    """
    flags = []
    carrier = record.get("insurance_carrier", "")

    # ONE CALL: contract likely terminated — $0 since 2025
    if carrier == "ONE CALL":
        flags.append("ONE CALL: contract may be terminated (revenue dropped to $0 in 2025)")

    # W/C: declining 63% — check if still active
    if carrier == "W/C":
        flags.append("W/C: Workers Comp volume declining sharply — verify claim is active")

    # SELF PAY: declining 88% — check pricing
    if carrier == "SELF PAY":
        flags.append("SELF PAY: volume down 88% — verify pricing is competitive")

    # COMP: typically $0 payments
    if carrier == "COMP":
        flags.append("COMP: complimentary/charity — expect $0 or near-$0 payment")

    # X: unknown payer — needs reclassification
    if carrier == "X":
        flags.append("X: unknown payer code — needs reclassification")

    return flags
