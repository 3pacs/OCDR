"""
Pattern Clustering Engine.

Manages the chart_number (BillingRecord.patient_id) ↔ topaz_id
(ERA claim_id / Topaz billing system ID) crosswalk.

Two modes of operation:
  1. DIRECT CROSSWALK: Parse Topaz server export files (.NET extensionless
     files) that contain explicit chart_number ↔ topaz_id mappings. This is
     the authoritative source — no offset or pattern guessing needed.

  2. PATTERN ANALYSIS: When direct exports aren't available, analyze
     confirmed auto-matcher results to discover structural relationships
     (offsets, prefixes, etc.) and propagate them.

The direct crosswalk is always preferred when data is available.
"""

import logging
from collections import Counter

from rapidfuzz import fuzz
from sqlalchemy import func

from app.models import db, BillingRecord

logger = logging.getLogger(__name__)


def analyze_crosswalk() -> dict:
    """
    Analyze Jacket ID (patient_id) <-> Topaz ID pairs.

    If both IDs are populated from the spreadsheet (direct mapping),
    reports coverage stats. Otherwise falls back to pattern analysis
    for offset/prefix/suffix relationships.
    """
    pairs = db.session.query(
        BillingRecord.patient_id, BillingRecord.topaz_patient_id, BillingRecord.patient_name
    ).filter(
        BillingRecord.patient_id.is_not(None),
        BillingRecord.topaz_patient_id.is_not(None),
    ).all()

    if not pairs:
        return {
            "status": "no_crosswalk_data",
            "message": "No billing records have both Jacket ID and Topaz ID. Import your OCMRI spreadsheet — both columns will be mapped automatically.",
            "total_pairs": 0,
        }

    # Deduplicate to unique (jacket_id, topaz_id) pairs
    unique_pairs = {}
    for jacket_id, topaz_id, patient_name in pairs:
        key = (jacket_id, topaz_id)
        if key not in unique_pairs:
            unique_pairs[key] = patient_name

    # Count unique Jacket IDs and Topaz IDs
    unique_jacket_ids = len({k[0] for k in unique_pairs.keys()})
    unique_topaz_ids = len({k[1] for k in unique_pairs.keys()})

    # Analyze relationship type
    patterns = {
        "direct_equal": 0,
        "numeric_offset": Counter(),
        "string_prefix": 0,
        "string_suffix": 0,
        "no_pattern": 0,
    }

    offsets = []

    for (jacket_id, topaz_id), patient_name in unique_pairs.items():
        jacket_str = str(jacket_id).strip()
        topaz_str = str(topaz_id).strip()

        # Pattern 1: Direct equality
        if jacket_str == topaz_str:
            patterns["direct_equal"] += 1
            continue

        # Pattern 2: Numeric offset
        try:
            jacket_int = int(jacket_str)
            topaz_int = int(topaz_str)
            offset = topaz_int - jacket_int
            offsets.append(offset)
            patterns["numeric_offset"][offset] += 1
            continue
        except (ValueError, TypeError):
            pass

        # Pattern 3: Prefix/suffix relationship
        if topaz_str.startswith(jacket_str) or jacket_str.startswith(topaz_str):
            patterns["string_prefix"] += 1
            continue
        if topaz_str.endswith(jacket_str) or jacket_str.endswith(topaz_str):
            patterns["string_suffix"] += 1
            continue

        # Pattern 4: Zero-padding equivalence
        try:
            if int(jacket_str) == int(topaz_str):
                patterns["direct_equal"] += 1
                continue
        except (ValueError, TypeError):
            pass

        patterns["no_pattern"] += 1

    # Find dominant offset if any
    dominant_offset = None
    dominant_offset_count = 0
    if patterns["numeric_offset"]:
        dominant_offset, dominant_offset_count = patterns["numeric_offset"].most_common(1)[0]

    total = len(unique_pairs)

    unique_offset_count = len(patterns["numeric_offset"])
    has_dominant_offset = (
        dominant_offset is not None and
        dominant_offset_count >= total * 0.5
    )

    if has_dominant_offset:
        mapping_type = "offset"
    elif unique_offset_count > total * 0.5 or patterns["no_pattern"] > total * 0.3:
        mapping_type = "direct"
    elif patterns["direct_equal"] > total * 0.5:
        mapping_type = "equal"
    else:
        mapping_type = "mixed"

    return {
        "total_pairs": total,
        "unique_jacket_ids": unique_jacket_ids,
        "unique_topaz_ids": unique_topaz_ids,
        "mapping_type": mapping_type,
        "patterns": {
            "direct_equal": patterns["direct_equal"],
            "numeric_offset_total": sum(patterns["numeric_offset"].values()),
            "unique_offsets": unique_offset_count,
            "top_offsets": [
                {"offset": off, "count": cnt}
                for off, cnt in patterns["numeric_offset"].most_common(5)
            ],
            "string_prefix": patterns["string_prefix"],
            "string_suffix": patterns["string_suffix"],
            "no_pattern": patterns["no_pattern"],
        },
        "dominant_offset": dominant_offset,
        "dominant_offset_count": dominant_offset_count,
        "dominant_offset_pct": round(dominant_offset_count / total * 100, 1) if total > 0 and dominant_offset_count > 0 else 0,
        "sample_pairs": [
            {"jacket_id": str(j), "topaz_id": str(t), "patient": n}
            for (j, t), n in list(unique_pairs.items())[:20]
        ],
    }


def propagate_topaz_ids(offset: int | None = None) -> dict:
    """
    Use discovered crosswalk patterns to assign topaz_id to billing records
    that don't have one yet.

    If offset is provided, applies: topaz_id = chart_number + offset
    Otherwise auto-detects the dominant offset from existing pairs.
    """
    if offset is None:
        analysis = analyze_crosswalk()
        if analysis.get("dominant_offset") is None:
            return {
                "status": "no_pattern",
                "message": "No dominant offset pattern found. Run the auto-matcher first to build crosswalk data.",
                "propagated": 0,
            }
        offset = analysis["dominant_offset"]
        confidence_pct = analysis["dominant_offset_pct"]
        if confidence_pct < 50:
            return {
                "status": "low_confidence",
                "message": f"Dominant offset {offset} only covers {confidence_pct}% of pairs. Not reliable enough to auto-propagate.",
                "propagated": 0,
                "offset": offset,
                "confidence_pct": confidence_pct,
            }

    records = BillingRecord.query.filter(
        BillingRecord.patient_id.is_not(None),
        BillingRecord.topaz_patient_id.is_(None),
    ).all()

    propagated = 0
    for br in records:
        try:
            chart_int = int(br.patient_id)
            br.topaz_patient_id = str(chart_int + offset)
            propagated += 1
        except (ValueError, TypeError):
            continue

    if propagated > 0:
        db.session.commit()

    logger.info(f"Propagated topaz_id to {propagated} records using offset {offset}")

    return {
        "status": "success",
        "offset_used": offset,
        "propagated": propagated,
        "total_without_topaz": len(records),
    }


def get_crosswalk_stats() -> dict:
    """Quick stats on crosswalk coverage."""
    total_count = db.session.query(func.count(BillingRecord.id)).scalar() or 0
    chart_count = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.patient_id.is_not(None)
    ).scalar() or 0
    topaz_count = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.topaz_patient_id.is_not(None)
    ).scalar() or 0
    both_count = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.patient_id.is_not(None),
        BillingRecord.topaz_patient_id.is_not(None),
    ).scalar() or 0

    return {
        "total_records": total_count,
        "has_chart_number": chart_count,
        "has_topaz_id": topaz_count,
        "has_both": both_count,
        "missing_topaz": chart_count - both_count,
    }


# ============================================================
# DIRECT CROSSWALK from Topaz export files
# ============================================================

def apply_topaz_crosswalk(crosswalk_pairs: list[dict]) -> dict:
    """
    Apply chart_number ↔ topaz_id crosswalk pairs from a Topaz export file.

    Each pair is a dict that may contain:
      - chart_number: str (matches BillingRecord.patient_id)
      - topaz_id: str (the Topaz billing system ID)
      - patient_name: str (optional, for verification)

    Returns summary of updates applied.
    """
    if not crosswalk_pairs:
        return {"status": "empty", "message": "No crosswalk pairs provided", "applied": 0}

    records_missing_topaz = BillingRecord.query.filter(
        BillingRecord.topaz_patient_id.is_(None)
    ).all()

    # Build indexes
    by_chart_number: dict[str, list] = {}
    for br in records_missing_topaz:
        if br.patient_id is not None:
            key = str(br.patient_id).strip()
            by_chart_number.setdefault(key, []).append(br)

    by_name: dict[str, list] = {}
    for br in records_missing_topaz:
        if br.patient_name:
            norm = br.patient_name.upper().strip()
            by_name.setdefault(norm, []).append(br)

    applied = 0
    skipped_no_match = 0
    skipped_name_mismatch = 0
    name_matched = 0
    updated_ids: set[int] = set()
    fuzzy_attempts = 0
    MAX_FUZZY = 500

    for pair in crosswalk_pairs:
        chart_num = str(pair.get("chart_number", "")).strip() if pair.get("chart_number") else None
        topaz_id = str(pair.get("topaz_id", "")).strip() if pair.get("topaz_id") else None
        patient_name = pair.get("patient_name", "")

        if not topaz_id:
            skipped_no_match += 1
            continue

        matched_this_pair = False

        # Strategy 1: Chart_number match WITH name corroboration
        if chart_num:
            candidates = by_chart_number.get(chart_num, [])
            if candidates and patient_name:
                name_upper = patient_name.upper().strip()
                for br in candidates:
                    if br.id in updated_ids:
                        continue
                    br_name = br.patient_name.upper().strip() if br.patient_name else ""
                    name_score = fuzz.token_sort_ratio(name_upper, br_name) if br_name else 0
                    if name_score >= 90:
                        br.topaz_patient_id = topaz_id
                        updated_ids.add(br.id)
                        applied += 1
                        matched_this_pair = True
                    else:
                        skipped_name_mismatch += 1
            elif candidates:
                for br in candidates:
                    if br.id in updated_ids:
                        continue
                    br.topaz_patient_id = topaz_id
                    updated_ids.add(br.id)
                    applied += 1
                    matched_this_pair = True

        # Strategy 2: Name-based match if chart didn't match
        if not matched_this_pair and patient_name:
            name_upper = patient_name.upper().strip()
            exact_matches = by_name.get(name_upper, [])
            for br in exact_matches:
                if br.id in updated_ids:
                    continue
                br.topaz_patient_id = topaz_id
                updated_ids.add(br.id)
                applied += 1
                name_matched += 1

            if not exact_matches and len(name_upper) > 3 and fuzzy_attempts < MAX_FUZZY:
                fuzzy_attempts += 1
                best_score = 0
                best_brs = None
                for norm_name, brs in by_name.items():
                    score = fuzz.token_sort_ratio(name_upper, norm_name)
                    if score >= 95 and score > best_score:
                        best_score = score
                        best_brs = brs
                        if score == 100:
                            break
                if best_brs:
                    for br in best_brs:
                        if br.id in updated_ids:
                            continue
                        br.topaz_patient_id = topaz_id
                        updated_ids.add(br.id)
                        applied += 1
                        name_matched += 1

    if applied > 0:
        db.session.commit()

    logger.info(
        f"Topaz crosswalk: applied {applied} ({name_matched} by name), "
        f"skipped {skipped_no_match} (no topaz_id), "
        f"skipped {skipped_name_mismatch} (name mismatch), "
        f"fuzzy attempts {fuzzy_attempts}/{MAX_FUZZY}"
    )

    return {
        "status": "success" if applied > 0 else "no_matches",
        "total_pairs": len(crosswalk_pairs),
        "applied": applied,
        "by_chart_number": applied - name_matched,
        "by_name_match": name_matched,
        "records_needing_topaz": len(records_missing_topaz),
        "skipped_no_topaz_id": skipped_no_match,
        "skipped_name_mismatch": skipped_name_mismatch,
    }
