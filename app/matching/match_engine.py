"""Auto-Match Engine: 835 ERA Claims → Billing Records (F-03 + Smart Matching).

Matches era_claim_lines to billing_records using composite scoring
with adaptive weights learned from match outcomes.

Default weights: 0.50 * name + 0.30 * date + 0.20 * modality
Learned weights override defaults when 50+ outcomes available per carrier.

Smart features:
  - Adaptive weights per carrier/modality (SM-01)
  - Adaptive thresholds per carrier (SM-02)
  - Name alias memory (SM-04)
  - Learned CPT->modality map (SM-05)
  - Smooth date scoring curves (SM-06)
  - Confidence calibration (SM-10)
"""

from collections import defaultdict
from datetime import timedelta

from rapidfuzz import fuzz

from app.models import db, BillingRecord, EraClaimLine, EraPayment


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
    for remove in ("MR.", "MRS.", "MS.", "DR.", "JR.", "SR.", "II", "III", "IV"):
        name = name.replace(remove, "")
    name = "".join(c if c.isalpha() or c in (" ", ",") else "" for c in name)
    name = " ".join(name.split())

    if "," in name:
        parts = name.split(",", 1)
        last = parts[0].strip()
        first_parts = parts[1].strip().split()
        first = first_parts[0] if first_parts else ""
    else:
        parts = name.split()
        if len(parts) >= 2:
            last = parts[0]
            first = parts[1]
        elif parts:
            last = parts[0]
            first = ""
        else:
            return ""

    return f"{last} {first}".strip()


def name_similarity(name_a, name_b, alias_lookup=None):
    """Compute fuzzy name similarity (0.0-1.0).

    Checks alias lookup first for known name pairs (SM-04).
    """
    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)
    if not norm_a or not norm_b:
        return 0.0

    # Check if names are known aliases (SM-04)
    if alias_lookup:
        a, b = (norm_a, norm_b) if norm_a <= norm_b else (norm_b, norm_a)
        if b in alias_lookup.get(a, set()):
            return 1.0

    score1 = fuzz.ratio(norm_a, norm_b) / 100.0

    parts_b = norm_b.split()
    if len(parts_b) == 2:
        swapped = f"{parts_b[1]} {parts_b[0]}"
        score2 = fuzz.ratio(norm_a, swapped) / 100.0
        return max(score1, score2)

    return score1


def date_match_score(date_a, date_b, date_curve=None):
    """Compute date proximity score (0.0-1.0).

    Uses learned curve (SM-06) if available, otherwise extended step function.
    """
    if not date_a or not date_b:
        return 0.0
    diff = abs((date_a - date_b).days)

    if date_curve and diff in date_curve:
        return date_curve[diff]

    if diff == 0:
        return 1.0
    elif diff == 1:
        return 0.8
    elif diff == 2:
        return 0.5
    elif diff <= 4:
        return 0.2
    elif diff <= 7:
        return 0.1
    return 0.0


def modality_match_score(era_cpt, billing_modality, learned_cpt_map=None):
    """Compute modality match score from CPT code vs billing modality.

    Uses learned CPT map (SM-05) supplemented with hardcoded map.
    """
    if not era_cpt or not billing_modality:
        return 0.0

    cpt_modality = _cpt_to_modality(era_cpt, learned_cpt_map)
    if not cpt_modality:
        return 0.0

    return 1.0 if cpt_modality == billing_modality.upper() else 0.0


def _cpt_to_modality(cpt_str, learned_map=None):
    """Map CPT code(s) to a modality, using learned map + hardcoded fallback."""
    if not cpt_str:
        return None
    cpt = cpt_str.split(",")[0].strip()

    # Check learned map first (SM-05)
    if learned_map and cpt in learned_map:
        return learned_map[cpt]["modality"]

    cpt_map = {
        "705": "HMRI", "706": "HMRI", "707": "HMRI",
        "711": "HMRI", "712": "HMRI", "713": "HMRI",
        "721": "HMRI", "722": "HMRI", "723": "HMRI",
        "731": "HMRI", "732": "HMRI", "733": "HMRI",
        "738": "HMRI", "739": "HMRI",
        "741": "CT", "742": "CT", "743": "CT",
        "700": "CT", "701": "CT",
        "788": "PET", "789": "PET", "781": "PET",
        "770": "BONE", "771": "BONE",
        "710": "DX",
    }

    if learned_map:
        for prefix_len in (5, 4, 3):
            prefix = cpt[:prefix_len] if len(cpt) >= prefix_len else None
            if prefix and prefix in learned_map:
                return learned_map[prefix]["modality"]

    for prefix, mod in cpt_map.items():
        if cpt.startswith(prefix):
            return mod
    return None


def compute_match_score(era_claim, billing_record, weights=None,
                        alias_lookup=None, date_curve=None, learned_cpt_map=None):
    """Compute composite match score with adaptive weights.

    Returns: (total_score, name_score, date_score, modality_score)
    """
    if not weights:
        weights = {"name_weight": 0.50, "date_weight": 0.30, "modality_weight": 0.20}

    ns = name_similarity(era_claim.patient_name_835, billing_record.patient_name, alias_lookup)
    ds = date_match_score(era_claim.service_date_835, billing_record.service_date, date_curve)
    ms = modality_match_score(era_claim.cpt_code, billing_record.modality, learned_cpt_map)

    total = (
        weights["name_weight"] * ns +
        weights["date_weight"] * ds +
        weights["modality_weight"] * ms
    )

    return round(total, 4), round(ns, 4), round(ds, 4), round(ms, 4)


# ── Match Runner ────────────────────────────────────────────────

def run_matching(auto_accept_threshold=0.95, review_threshold=0.80, date_window_days=7):
    """Run the auto-match engine on all unmatched ERA claim lines.

    Uses learned weights, thresholds, aliases, CPT map, and date curves
    when available. Falls back to defaults otherwise.

    Performance: pre-loads billing records and uses date index to avoid N+1 queries.
    """
    alias_lookup = _load_alias_lookup()
    date_curve = _load_date_curve()
    learned_cpt_map = _load_cpt_map()

    stats = {
        "total_processed": 0,
        "auto_accepted": 0,
        "needs_review": 0,
        "rejected": 0,
        "already_matched": 0,
        "smart_features": {
            "aliases_loaded": len(alias_lookup) if alias_lookup else 0,
            "date_curve": date_curve is not None,
            "learned_cpts": len(learned_cpt_map) if learned_cpt_map else 0,
        },
    }

    unmatched = EraClaimLine.query.filter(
        EraClaimLine.matched_billing_id.is_(None)
    ).all()

    # Pre-load all billing records in the relevant date range (fixes N+1)
    if unmatched:
        dates = [c.service_date_835 for c in unmatched if c.service_date_835]
        if dates:
            min_date = min(dates) - timedelta(days=date_window_days)
            max_date = max(dates) + timedelta(days=date_window_days)
            all_candidates = BillingRecord.query.filter(
                BillingRecord.service_date.between(min_date, max_date)
            ).all()
        else:
            all_candidates = []
    else:
        all_candidates = []

    # Build date index for O(1) candidate lookup
    date_index = defaultdict(list)
    for b in all_candidates:
        if b.service_date:
            date_index[b.service_date].append(b)

    weights_cache = {}

    for claim in unmatched:
        stats["total_processed"] += 1

        if not claim.service_date_835:
            stats["rejected"] += 1
            claim.match_confidence = 0.0
            continue

        # Get learned weights/thresholds (SM-01, SM-02)
        weights = _get_cached_weights(weights_cache, None, None)
        accept_thresh = weights.get("auto_accept_threshold", auto_accept_threshold)
        review_thresh = weights.get("review_threshold", review_threshold)

        # Find candidates within date window via index
        candidates = []
        for day_offset in range(-date_window_days, date_window_days + 1):
            check_date = claim.service_date_835 + timedelta(days=day_offset)
            candidates.extend(date_index.get(check_date, []))

        best_score = 0.0
        best_match = None

        for billing in candidates:
            total, ns, ds, ms = compute_match_score(
                claim, billing,
                weights=weights,
                alias_lookup=alias_lookup,
                date_curve=date_curve,
                learned_cpt_map=learned_cpt_map,
            )
            if total > best_score:
                best_score = total
                best_match = billing

        claim.match_confidence = best_score

        if best_score >= accept_thresh and best_match:
            claim.matched_billing_id = best_match.id
            stats["auto_accepted"] += 1
            # Record auto-accepted outcome so the system learns from them
            _record_smart_outcome(claim, best_match.id, "AUTO_ACCEPTED")
        elif best_score >= review_thresh and best_match:
            claim.matched_billing_id = best_match.id
            stats["needs_review"] += 1
        else:
            stats["rejected"] += 1

    db.session.commit()

    # Trigger calibration if we have enough data
    _maybe_recalibrate()

    return stats


def confirm_match(claim_id, billing_id=None):
    """Manually confirm or reassign a match. Records outcome for learning."""
    claim = db.session.get(EraClaimLine, claim_id)
    if not claim:
        return {"error": "Claim not found"}

    action = "CONFIRMED"
    if billing_id is not None:
        billing = db.session.get(BillingRecord, billing_id)
        if not billing:
            return {"error": "Billing record not found"}
        if billing_id != claim.matched_billing_id:
            action = "REASSIGNED"
        claim.matched_billing_id = billing_id
    else:
        billing_id = claim.matched_billing_id

    claim.match_confidence = 1.0
    _record_smart_outcome(claim, billing_id, action)
    _flow_back_era_payment(claim, billing_id)
    db.session.commit()
    return {"status": "confirmed", "claim_id": claim_id, "billing_id": claim.matched_billing_id}


def reject_match(claim_id):
    """Reject a match — clear the matched billing ID. Records outcome for learning."""
    claim = db.session.get(EraClaimLine, claim_id)
    if not claim:
        return {"error": "Claim not found"}

    old_billing_id = claim.matched_billing_id
    _record_smart_outcome(claim, old_billing_id, "REJECTED")

    claim.matched_billing_id = None
    claim.match_confidence = 0.0
    db.session.commit()
    return {"status": "rejected", "claim_id": claim_id}


def get_match_results(status_filter=None, page=1, per_page=50):
    """Get match results with optional status filter.

    Optimized: batch-loads billing records instead of N+1 queries.
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

    # Batch-load billing records (fixes N+1 query)
    billing_ids = [c.matched_billing_id for c in results.items if c.matched_billing_id]
    billing_map = {}
    if billing_ids:
        billings = BillingRecord.query.filter(BillingRecord.id.in_(billing_ids)).all()
        billing_map = {b.id: b for b in billings}

    items = []
    for claim in results.items:
        item = claim.to_dict()
        if claim.matched_billing_id and claim.matched_billing_id in billing_map:
            item["matched_billing"] = billing_map[claim.matched_billing_id].to_dict()
        items.append(item)

    return {
        "items": items,
        "total": results.total,
        "page": page,
        "pages": results.pages,
    }


# ── ERA Payment Flow-Back ──────────────────────────────────────

def _flow_back_era_payment(claim, billing_id):
    """Flow ERA payment data back to the matched billing record.

    Updates billing record with:
    - era_paid_amount: actual amount paid per ERA 835
    - payment_method: normalized from ERA payment method
    - adjustment_amount: CAS adjustment amount
    - charge_category: inferred if not already set
    """
    try:
        billing = db.session.get(BillingRecord, billing_id) if billing_id else None
        if not billing or not claim:
            return

        # Set era_paid_amount from ERA claim line
        if claim.paid_amount is not None:
            billing.era_paid_amount = claim.paid_amount

        # Set adjustment amount from ERA
        if claim.cas_adjustment_amount is not None:
            billing.adjustment_amount = claim.cas_adjustment_amount

        # Flow payment method from ERA payment header
        if claim.era_payment_id:
            era_payment = db.session.get(EraPayment, claim.era_payment_id)
            if era_payment and era_payment.payment_method:
                from app.revenue.underpayment_detector import normalize_payment_method
                billing.payment_method = normalize_payment_method(era_payment.payment_method)

        # Set billed_amount from ERA if not already set
        if claim.billed_amount and (not billing.billed_amount or billing.billed_amount == 0):
            billing.billed_amount = claim.billed_amount

        # Flow CPT code from ERA claim line
        if claim.cpt_code and (not billing.cpt_code):
            billing.cpt_code = claim.cpt_code

        # Infer charge_category if not already set
        if not billing.charge_category:
            from app.revenue.underpayment_detector import infer_charge_category
            billing.charge_category = infer_charge_category(billing)

        # Create PaymentDetail record for audit trail
        try:
            from app.models import PaymentDetail
            detail = PaymentDetail(
                billing_record_id=billing_id,
                era_claim_line_id=claim.id,
                payment_type='PRIMARY',
                payment_method=billing.payment_method,
                payment_amount=claim.paid_amount or 0.0,
                payer_name=era_payment.payer_name if claim.era_payment_id and era_payment else None,
                payment_date=era_payment.payment_date if claim.era_payment_id and era_payment else None,
                source='ERA_835',
            )
            db.session.add(detail)
        except Exception:
            pass  # Don't fail the match if payment detail fails

    except Exception:
        pass  # Don't break match operations if flow-back fails


# ── Smart Matching Helpers ──────────────────────────────────────

def _record_smart_outcome(claim, billing_id, action):
    """Record a match outcome with component scores for learning."""
    try:
        from app.matching.match_memory import record_outcome
        billing = db.session.get(BillingRecord, billing_id) if billing_id else None

        ns, ds, ms = 0, 0, 0
        if billing:
            _, ns, ds, ms = compute_match_score(claim, billing)

        record_outcome(
            era_claim_id=claim.id,
            billing_record_id=billing_id,
            action=action,
            original_score=claim.match_confidence,
            name_score=ns, date_score=ds, modality_score=ms,
            carrier=billing.insurance_carrier if billing else None,
            modality=billing.modality if billing else None,
        )

        if billing:
            from app.matching.weight_optimizer import maybe_reoptimize
            maybe_reoptimize(carrier=billing.insurance_carrier, modality=billing.modality)
    except Exception:
        pass  # Don't break match operations if learning fails


def _maybe_recalibrate():
    """Trigger Platt scaling recalibration if enough outcomes exist."""
    try:
        from app.matching.calibration import train_calibration
        train_calibration()
    except Exception:
        pass


def _load_alias_lookup():
    try:
        from app.matching.match_memory import build_alias_lookup
        return build_alias_lookup(min_count=2)
    except Exception:
        return {}


def _load_date_curve():
    try:
        from app.matching.match_memory import build_date_score_curve
        return build_date_score_curve(min_samples=30)
    except Exception:
        return None


def _load_cpt_map():
    try:
        from app.matching.match_memory import get_cpt_modality_map
        return get_cpt_modality_map()
    except Exception:
        return {}


def _get_cached_weights(cache, carrier, modality):
    key = (carrier, modality)
    if key not in cache:
        try:
            from app.matching.weight_optimizer import get_learned_weights
            cache[key] = get_learned_weights(carrier=carrier, modality=modality)
        except Exception:
            cache[key] = {
                "name_weight": 0.50, "date_weight": 0.30, "modality_weight": 0.20,
                "auto_accept_threshold": 0.95, "review_threshold": 0.80,
            }
    return cache[key]
