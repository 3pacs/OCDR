"""Auto-Match Engine: 835 ERA Claims → Billing Records (F-03).

Matches era_claim_lines to billing_records using composite scoring:
  score = 0.50 * name_similarity + 0.30 * date_match + 0.20 * modality_match

Thresholds:
  >= 0.95  → auto-accept
  0.80-0.95 → manual review
  < 0.80  → reject
"""

from datetime import timedelta

from rapidfuzz import fuzz

from app.models import db, BillingRecord, EraClaimLine


# ── Name normalization ──────────────────────────────────────────

def normalize_name(name):
    """Normalize a patient name for matching.

    Handles: LAST, FIRST / FIRST LAST / LAST FIRST MIDDLE
    Strips titles, middle initials, punctuation.
    Returns uppercase "LAST FIRST" canonical form.
    """
    if not name:
        return ""
    name = name.upper().strip()
    # Remove common titles/suffixes
    for remove in ("MR.", "MRS.", "MS.", "DR.", "JR.", "SR.", "II", "III", "IV"):
        name = name.replace(remove, "")
    # Remove punctuation except comma
    name = "".join(c if c.isalpha() or c in (" ", ",") else "" for c in name)
    name = " ".join(name.split())  # collapse whitespace

    if "," in name:
        parts = name.split(",", 1)
        last = parts[0].strip()
        first_parts = parts[1].strip().split()
        first = first_parts[0] if first_parts else ""
    else:
        parts = name.split()
        if len(parts) >= 2:
            # Assume LAST FIRST or FIRST LAST — try both and use best match later
            last = parts[0]
            first = parts[1]
        elif parts:
            last = parts[0]
            first = ""
        else:
            return ""

    return f"{last} {first}".strip()


def name_similarity(name_a, name_b):
    """Compute fuzzy name similarity (0.0–1.0)."""
    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)
    if not norm_a or not norm_b:
        return 0.0

    # Try both orderings for "FIRST LAST" vs "LAST FIRST"
    score1 = fuzz.ratio(norm_a, norm_b) / 100.0

    # Also try swapping first/last of name_b
    parts_b = norm_b.split()
    if len(parts_b) == 2:
        swapped = f"{parts_b[1]} {parts_b[0]}"
        score2 = fuzz.ratio(norm_a, swapped) / 100.0
        return max(score1, score2)

    return score1


def date_match_score(date_a, date_b):
    """Compute date proximity score (0.0–1.0).

    exact     → 1.0
    ±1 day    → 0.8
    ±2 days   → 0.5
    otherwise → 0.0
    """
    if not date_a or not date_b:
        return 0.0
    diff = abs((date_a - date_b).days)
    if diff == 0:
        return 1.0
    elif diff == 1:
        return 0.8
    elif diff == 2:
        return 0.5
    return 0.0


def modality_match_score(era_cpt, billing_modality):
    """Compute modality match score from CPT code vs billing modality.

    Maps common CPT code prefixes to modalities, then compares.
    exact match → 1.0, else → 0.0
    """
    if not era_cpt or not billing_modality:
        return 0.0

    # CPT → modality mapping
    cpt_modality = _cpt_to_modality(era_cpt)
    if not cpt_modality:
        return 0.0

    return 1.0 if cpt_modality == billing_modality.upper() else 0.0


def _cpt_to_modality(cpt_str):
    """Map CPT code(s) to a modality."""
    if not cpt_str:
        return None
    # Take first CPT if comma-separated
    cpt = cpt_str.split(",")[0].strip()

    cpt_map = {
        # MRI codes (70xxx, 71xxx, 72xxx, 73xxx)
        "705": "HMRI", "706": "HMRI", "707": "HMRI",
        "711": "HMRI", "712": "HMRI", "713": "HMRI",
        "721": "HMRI", "722": "HMRI", "723": "HMRI",
        "731": "HMRI", "732": "HMRI", "733": "HMRI",
        "738": "HMRI", "739": "HMRI",
        # CT codes (74xxx, some 70xxx)
        "741": "CT", "742": "CT", "743": "CT",
        "700": "CT", "701": "CT",
        # PET codes (78xxx)
        "788": "PET", "789": "PET",
        "781": "PET",
        # Bone density (77xxx)
        "770": "BONE", "771": "BONE",
        # X-ray / DX (71xxx diagnostic)
        "710": "DX",
    }

    for prefix, mod in cpt_map.items():
        if cpt.startswith(prefix):
            return mod
    return None


def compute_match_score(era_claim, billing_record):
    """Compute composite match score between an ERA claim and a billing record.

    Returns float 0.0–1.0:
      0.50 * name_similarity + 0.30 * date_match + 0.20 * modality_match
    """
    name_score = name_similarity(era_claim.patient_name_835, billing_record.patient_name)
    date_score = date_match_score(era_claim.service_date_835, billing_record.service_date)
    mod_score = modality_match_score(era_claim.cpt_code, billing_record.modality)

    return round(0.50 * name_score + 0.30 * date_score + 0.20 * mod_score, 4)


# ── Match Runner ────────────────────────────────────────────────

def run_matching(auto_accept_threshold=0.95, review_threshold=0.80, date_window_days=2):
    """Run the auto-match engine on all unmatched ERA claim lines.

    For each unmatched claim line, searches billing_records within a date window,
    computes composite scores, and assigns the best match.

    Returns:
        dict: {
            "total_processed": int,
            "auto_accepted": int,
            "needs_review": int,
            "rejected": int,
            "already_matched": int,
        }
    """
    stats = {
        "total_processed": 0,
        "auto_accepted": 0,
        "needs_review": 0,
        "rejected": 0,
        "already_matched": 0,
    }

    # Get unmatched claim lines
    unmatched = EraClaimLine.query.filter(
        EraClaimLine.matched_billing_id.is_(None)
    ).all()

    for claim in unmatched:
        stats["total_processed"] += 1

        if not claim.service_date_835:
            stats["rejected"] += 1
            claim.match_confidence = 0.0
            continue

        # Search billing records within date window
        date_start = claim.service_date_835 - timedelta(days=date_window_days)
        date_end = claim.service_date_835 + timedelta(days=date_window_days)

        candidates = BillingRecord.query.filter(
            BillingRecord.service_date.between(date_start, date_end)
        ).all()

        best_score = 0.0
        best_match = None

        for billing in candidates:
            score = compute_match_score(claim, billing)
            if score > best_score:
                best_score = score
                best_match = billing

        claim.match_confidence = best_score

        if best_score >= auto_accept_threshold and best_match:
            claim.matched_billing_id = best_match.id
            stats["auto_accepted"] += 1
        elif best_score >= review_threshold and best_match:
            claim.matched_billing_id = best_match.id
            stats["needs_review"] += 1
        else:
            stats["rejected"] += 1

    db.session.commit()
    return stats


def confirm_match(claim_id, billing_id=None):
    """Manually confirm or reassign a match.

    If billing_id is provided, reassigns the match.
    Sets confidence to 1.0 (human confirmed).
    """
    claim = EraClaimLine.query.get(claim_id)
    if not claim:
        return {"error": "Claim not found"}

    if billing_id is not None:
        claim.matched_billing_id = billing_id

    claim.match_confidence = 1.0
    db.session.commit()
    return {"status": "confirmed", "claim_id": claim_id, "billing_id": claim.matched_billing_id}


def reject_match(claim_id):
    """Reject a match — clear the matched billing ID."""
    claim = EraClaimLine.query.get(claim_id)
    if not claim:
        return {"error": "Claim not found"}

    claim.matched_billing_id = None
    claim.match_confidence = 0.0
    db.session.commit()
    return {"status": "rejected", "claim_id": claim_id}


def get_match_results(status_filter=None, page=1, per_page=50):
    """Get match results with optional status filter.

    status_filter: 'auto_accepted' (>=0.95), 'review' (0.80-0.95), 'rejected' (<0.80), 'unmatched' (None)
    """
    query = EraClaimLine.query

    if status_filter == "auto_accepted":
        query = query.filter(EraClaimLine.match_confidence >= 0.95, EraClaimLine.matched_billing_id.isnot(None))
    elif status_filter == "review":
        query = query.filter(EraClaimLine.match_confidence >= 0.80, EraClaimLine.match_confidence < 0.95, EraClaimLine.matched_billing_id.isnot(None))
    elif status_filter == "rejected":
        query = query.filter(EraClaimLine.match_confidence < 0.80, EraClaimLine.match_confidence.isnot(None))
    elif status_filter == "unmatched":
        query = query.filter(EraClaimLine.match_confidence.is_(None))

    results = query.order_by(EraClaimLine.match_confidence.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for claim in results.items:
        item = claim.to_dict()
        if claim.matched_billing_id:
            billing = BillingRecord.query.get(claim.matched_billing_id)
            if billing:
                item["matched_billing"] = billing.to_dict()
        items.append(item)

    return {
        "items": items,
        "total": results.total,
        "page": page,
        "pages": results.pages,
    }
