"""Auto-Match Engine: 835 ERA Claims -> Billing Records.

14-pass progressive matching algorithm (ported from Docker app):

  Pass 0:  Topaz ID       (claim_id == topaz_id crosswalk)            -> 99%
  Pass 0b: Claim ID -> patient_id (chart number cross-reference)      -> 92%
  Pass 1:  Exact composite (name + service_date + amount)             -> 99%
  Pass 2:  Strong fuzzy   (name>=95 + service_date + CPT/modality)    -> 95%
  Pass 3:  Medium fuzzy   (name>=90 + service_date)                   -> 85%
  Pass 4:  Weak fuzzy     (name>=70 + service_date +/-3 days)         -> 70%
  Pass 4b: Wider date     (name>=70 + service_date +/-7 days)         -> 60%
  Pass 4c: Wide date      (name>=70 + service_date +/-14 days)        -> 55%
  Pass 4d: Very wide date (name>=70 + service_date +/-30 days)        -> 50%
  Pass 5:  Amount-anchor  (carrier + service_date + billed amount)    -> 75%
  Pass 6:  Name + modality (no date required, name>=70 + modality)    -> 62%
  Pass 7:  Name + amount  (no date required, name>=70 + billed amt)   -> 65%
  Pass 8:  Name only      (no date required, name>=70, multi-record)  -> 55%
  Pass 9:  Broad fuzzy    (name>=70, scan all billing records)        -> 45%
  Pass S:  Supply linking  (HCPCS supply codes -> sibling procedures) -> 95%
  Pass 10: Auto-create    (stub billing record from ERA data)         -> 100%

Many-to-one: Multiple ERA claims can link to the same billing record
(original payment, adjustments, secondary payers, appeals). Billing
records are NOT removed from indexes after first match.

TOPAZ PREFIX ENCODING:
  10000000+: Primary insurance billing
  20000000+: Secondary insurance billing
  30000000+: Tertiary insurance billing
  70000000+: Patient copay/responsibility
  To extract real PatientID: claim_id % 10000000
"""

import logging
from collections import defaultdict
from datetime import date, timedelta

from rapidfuzz import fuzz

from app.models import db, BillingRecord, EraClaimLine, EraPayment
from app.matching.icd10_modality_map import diagnosis_modality_score

logger = logging.getLogger(__name__)

BATCH_SIZE = 500

# ── CPT -> Modality Map ──────────────────────────────────────────

CPT_TO_MODALITY = {
    # CT
    "70450": "CT", "70460": "CT", "70470": "CT",
    "70480": "CT", "70481": "CT", "70482": "CT",
    "70486": "CT", "70487": "CT", "70488": "CT",
    "70490": "CT", "70491": "CT", "70492": "CT",
    "71250": "CT", "71260": "CT", "71270": "CT", "71275": "CT",
    "72125": "CT", "72126": "CT", "72127": "CT",
    "72128": "CT", "72129": "CT", "72130": "CT",
    "72131": "CT", "72132": "CT", "72133": "CT",
    "72191": "CT",
    "72192": "CT", "72193": "CT", "72194": "CT",
    "73200": "CT", "73201": "CT", "73202": "CT",
    "73700": "CT", "73701": "CT", "73702": "CT",
    "74150": "CT", "74160": "CT", "74170": "CT",
    "74174": "CT", "74176": "CT", "74177": "CT", "74178": "CT",
    "76380": "CT",
    # MRI (HMRI = high-field MRI)
    "70336": "HMRI",
    "70540": "HMRI", "70542": "HMRI", "70543": "HMRI",
    "70551": "HMRI", "70552": "HMRI", "70553": "HMRI",
    "70554": "HMRI", "70555": "HMRI",
    "71550": "HMRI", "71551": "HMRI", "71552": "HMRI",
    "72141": "HMRI", "72142": "HMRI", "72146": "HMRI",
    "72147": "HMRI", "72148": "HMRI", "72149": "HMRI",
    "72156": "HMRI", "72157": "HMRI", "72158": "HMRI",
    "72195": "HMRI", "72196": "HMRI", "72197": "HMRI",
    "73218": "HMRI", "73219": "HMRI", "73220": "HMRI",
    "73221": "HMRI", "73222": "HMRI", "73223": "HMRI",
    "73718": "HMRI", "73719": "HMRI", "73720": "HMRI",
    "73721": "HMRI", "73722": "HMRI", "73723": "HMRI",
    "74181": "HMRI", "74182": "HMRI", "74183": "HMRI",
    "77084": "HMRI",
    # PET and PET/CT
    "78429": "PET", "78430": "PET", "78431": "PET", "78432": "PET",
    "78459": "PET",
    "78491": "PET", "78492": "PET",
    "78608": "PET", "78609": "PET",
    "78811": "PET", "78812": "PET", "78813": "PET",
    "78814": "PET", "78815": "PET", "78816": "PET",
    # Bone scan
    "78300": "BONE", "78305": "BONE", "78306": "BONE",
    "78315": "BONE", "78399": "BONE",
    # X-ray / DX
    "71045": "DX", "71046": "DX", "71047": "DX", "71048": "DX",
    "72020": "DX", "72040": "DX", "72050": "DX",
    "72070": "DX", "72072": "DX", "72074": "DX",
    "72080": "DX", "72100": "DX", "72110": "DX",
    "73000": "DX", "73010": "DX", "73020": "DX", "73030": "DX",
    "73060": "DX", "73070": "DX", "73080": "DX", "73090": "DX",
    "73500": "DX", "73510": "DX", "73520": "DX", "73521": "DX",
    "73550": "DX", "73560": "DX", "73562": "DX", "73564": "DX",
    "73590": "DX", "73600": "DX", "73610": "DX", "73620": "DX",
    # Ultrasound
    "76536": "US", "76604": "US", "76641": "US", "76642": "US",
    "76700": "US", "76705": "US", "76770": "US", "76775": "US",
    "76801": "US", "76805": "US", "76815": "US", "76817": "US",
    "76856": "US", "76857": "US",
    "93880": "US", "93925": "US", "93926": "US", "93970": "US", "93971": "US",
    # Mammography
    "77065": "MAMMO", "77066": "MAMMO", "77067": "MAMMO",
    # DEXA
    "77080": "DEXA", "77081": "DEXA", "77085": "DEXA", "77086": "DEXA",
    # Fluoroscopy
    "76000": "FLUORO", "76001": "FLUORO",
}

HCPCS_SUPPLY_CODES = {
    "A9576": "HMRI", "A9577": "HMRI", "A9578": "HMRI", "A9579": "HMRI",
    "A9585": "HMRI", "A9581": "HMRI", "A4641": "HMRI",
    "Q9965": "CT", "Q9966": "CT", "Q9967": "CT", "A9575": "CT",
    "A9580": "PET", "A9587": "PET", "A9588": "PET", "A9515": "PET",
    "A9590": "PET", "A9591": "PET", "A9597": "PET",
    "A9503": "BONE", "A9500": "BONE", "A9502": "BONE",
    "A9540": "BONE", "A9560": "BONE",
    "A4642": "DX", "Q9951": "CT", "Q9958": "CT", "Q9963": "CT",
}

CLAIM_STATUS_MAP = {
    "1": "PAID_PRIMARY", "2": "PAID_SECONDARY", "3": "PAID_TERTIARY",
    "4": "DENIED", "5": "PENDING", "10": "PENDING", "13": "PENDING",
    "19": "PAID_PRIMARY", "20": "PAID_SECONDARY", "22": "REVERSAL",
}
DENIAL_STATUSES = {"DENIED", "PENDING", "REVERSAL"}

TOPAZ_PREFIX_MOD = 10_000_000
TOPAZ_PREFIX_LABELS = {
    0: "direct", 1: "primary", 2: "secondary", 3: "tertiary",
    7: "copay", 8: "tier_8", 9: "tier_9",
}


# ── Name Normalization ────────────────────────────────────────────

def normalize_name(name):
    """Normalize patient name: uppercase, strip commas, remove initials, sort tokens.

    Order-independent: 'SMITH JOHN' and 'JOHN SMITH' produce the same key.
    """
    if not name:
        return ""
    cleaned = name.upper().strip().replace(",", " ")
    parts = cleaned.split()
    parts = [p for p in parts if len(p) > 1]
    parts.sort()
    return " ".join(parts).strip()


def _name_score_pair(name_a, name_b):
    """Score two normalized names using best of token_sort and token_set ratio."""
    if not name_a or not name_b:
        return 0
    return max(fuzz.token_sort_ratio(name_a, name_b),
               fuzz.token_set_ratio(name_a, name_b))


def _best_name_score(claim_name, br, billing_norm_names):
    """Get the best fuzzy name score for a billing record."""
    norm = billing_norm_names.get(br.id, "")
    return _name_score_pair(claim_name, norm)


def name_similarity(name_a, name_b, alias_lookup=None):
    """Compute fuzzy name similarity (0.0-1.0). Kept for SM learning compatibility."""
    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)
    if not norm_a or not norm_b:
        return 0.0
    if alias_lookup:
        a, b = (norm_a, norm_b) if norm_a <= norm_b else (norm_b, norm_a)
        if b in alias_lookup.get(a, set()):
            return 1.0
    return _name_score_pair(norm_a, norm_b) / 100.0


# ── Topaz ID Helpers ──────────────────────────────────────────────

def _strip_leading_zeros(s):
    stripped = s.lstrip("0")
    return stripped or "0"


def _decode_topaz_id(raw_id):
    """Decode Topaz prefixed PatientID -> (base_id_str, context)."""
    cleaned = raw_id.strip().lstrip("0") or "0"
    try:
        num = int(cleaned)
    except (ValueError, OverflowError):
        return cleaned, "unknown"
    if num >= TOPAZ_PREFIX_MOD:
        prefix_digit = num // TOPAZ_PREFIX_MOD
        base_id = num % TOPAZ_PREFIX_MOD
        context = TOPAZ_PREFIX_LABELS.get(prefix_digit, f"prefix_{prefix_digit}")
        return str(base_id), context
    return str(num), "direct"


def _all_topaz_variants(raw_id):
    """Generate all lookup keys for a Topaz ID."""
    keys = set()
    cleaned = raw_id.strip()
    keys.add(cleaned)
    keys.add(_strip_leading_zeros(cleaned))
    base_id, _ = _decode_topaz_id(cleaned)
    keys.add(base_id)
    keys.add(_strip_leading_zeros(base_id))
    keys.discard("")
    return list(keys)


# ── Modality Helpers ──────────────────────────────────────────────

def _is_supply_code(cpt_code):
    """Check if a CPT/HCPCS code is a supply/drug (not a procedure).

    Only matches known supply codes (A-codes for drugs/supplies, Q-codes for
    contrast agents). Does NOT treat all alpha-prefixed codes as supplies —
    G-codes (professional services), T-codes, etc. are legitimate procedures.
    """
    if not cpt_code:
        return False
    code = cpt_code.strip().upper()
    return code in HCPCS_SUPPLY_CODES


def _modality_matches(claim_modality, billing_modality):
    if not claim_modality or not billing_modality:
        return True
    return claim_modality.upper() == billing_modality.upper()


def modality_match_score(era_cpt, billing_modality, learned_cpt_map=None):
    """Compute modality match score (0 or 1). Kept for SM learning compatibility."""
    if not era_cpt or not billing_modality:
        return 0.0
    cpt = era_cpt.split(",")[0].strip()
    mod = CPT_TO_MODALITY.get(cpt)
    if not mod and learned_cpt_map and cpt in learned_cpt_map:
        mod = learned_cpt_map[cpt].get("modality")
    return 1.0 if mod and mod == billing_modality.upper() else 0.0


def date_match_score(date_a, date_b, date_curve=None):
    """Compute date proximity score (0.0-1.0). Kept for SM learning compatibility."""
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


def compute_match_score(era_claim, billing_record, weights=None,
                        alias_lookup=None, date_curve=None, learned_cpt_map=None):
    """Compute composite match score. Kept for SM learning/outcome recording."""
    if not weights:
        weights = {"name_weight": 0.50, "date_weight": 0.30, "modality_weight": 0.20}
    ns = name_similarity(era_claim.patient_name_835, billing_record.patient_name, alias_lookup)
    ds = date_match_score(era_claim.service_date_835, billing_record.service_date, date_curve)
    ms = modality_match_score(era_claim.cpt_code, billing_record.modality, learned_cpt_map)
    total = weights["name_weight"] * ns + weights["date_weight"] * ds + weights["modality_weight"] * ms
    return round(total, 4), round(ns, 4), round(ds, 4), round(ms, 4)


# ── Candidate Disambiguation ─────────────────────────────────────

def _pick_best_candidate(candidates, claim_date, claim_name, claim_modality,
                         billing_norm_names, claim_diagnosis_codes=None):
    """Pick best billing record from multiple candidates.
    Prioritizes: modality match > ICD-10 diagnosis fit > date match > name score.
    """
    if not candidates:
        return None, False
    if len(candidates) == 1:
        return candidates[0], False

    best_br = None
    best_score = -1
    for c in candidates:
        date_match = (c.service_date == claim_date) if claim_date else False
        n_score = _best_name_score(claim_name, c, billing_norm_names) if claim_name else 0
        mod_match = _modality_matches(claim_modality, c.modality)
        dx_score = diagnosis_modality_score(claim_diagnosis_codes, c.modality)
        combined = ((200 if mod_match else 0) +
                    (150 * dx_score) +
                    (100 if date_match else 0) +
                    n_score)
        if combined > best_score:
            best_score = combined
            best_br = c
    return best_br, True


# ── Single Claim Matcher (14 passes) ─────────────────────────────

def _match_single_claim(
    claim, claim_name, claim_date, claim_paid, claim_billed,
    claim_cpt, claim_modality, era_payment,
    billing_by_name_date, billing_by_date, billing_by_topaz_id,
    billing_by_patient_id, billing_norm_names,
    billing_by_name, billing_by_modality_name,
    billing_records_list=None, claim_diagnosis_codes=None,
):
    """Run matching passes for a single claim.
    Returns (billing_record, confidence, pass_name) or (None, 0, None).
    """

    # Pass 0: Topaz ID crosswalk match
    if claim.claim_id:
        topaz_key = claim.claim_id.strip()
        candidates = []
        for variant in _all_topaz_variants(topaz_key):
            candidates = billing_by_topaz_id.get(variant, [])
            if candidates:
                break
        if candidates:
            if len(candidates) == 1:
                return candidates[0], 0.99, "pass_0_topaz_id"
            best_br, _ = _pick_best_candidate(
                candidates, claim_date, claim_name, claim_modality,
                billing_norm_names, claim_diagnosis_codes)
            if best_br:
                return best_br, 0.97, "pass_0_topaz_id"

    # Pass 0b: Claim ID -> patient_id (chart number)
    if claim.claim_id:
        claim_id_stripped = claim.claim_id.strip()
        p0b_candidates = []
        for variant in _all_topaz_variants(claim_id_stripped):
            try:
                variant_int = int(variant)
                p0b_candidates = billing_by_patient_id.get(variant_int, [])
                if p0b_candidates:
                    break
            except (ValueError, OverflowError):
                continue
        if p0b_candidates:
            if len(p0b_candidates) == 1:
                return p0b_candidates[0], 0.92, "pass_0b_patient_id"
            best_br, _ = _pick_best_candidate(
                p0b_candidates, claim_date, claim_name, claim_modality,
                billing_norm_names, claim_diagnosis_codes)
            if best_br:
                date_match = (best_br.service_date == claim_date) if claim_date else False
                conf = 0.90 if date_match else 0.85
                return best_br, conf, "pass_0b_patient_id"

    # Pass 1: Exact composite (name + date + amount)
    if claim_name and claim_date:
        key = (claim_name, claim_date)
        candidates = billing_by_name_date.get(key, [])
        if len(candidates) == 1:
            return candidates[0], 0.99, "pass_1_exact"
        if len(candidates) > 1:
            if claim_modality:
                mod_matches = [br for br in candidates
                               if _modality_matches(claim_modality, br.modality)]
                if len(mod_matches) == 1:
                    return mod_matches[0], 0.99, "pass_1_exact"
                if mod_matches:
                    candidates = mod_matches
            for br in candidates:
                if claim_paid and br.total_payment:
                    if abs(float(br.total_payment) - claim_paid) < 0.01:
                        return br, 0.99, "pass_1_exact"
            # Multiple candidates, no amount disambiguator — pick best
            best_br, _ = _pick_best_candidate(
                candidates, claim_date, claim_name, claim_modality,
                billing_norm_names, claim_diagnosis_codes)
            if best_br:
                return best_br, 0.95, "pass_1_exact"

    # Pass 2: Strong fuzzy (name>=95 + date + CPT/modality)
    if claim_name and claim_date:
        date_candidates = billing_by_date.get(claim_date, [])
        for br in date_candidates:
            score = _best_name_score(claim_name, br, billing_norm_names)
            if score < 95:
                continue
            if claim_modality and br.modality and claim_modality.upper() == br.modality.upper():
                return br, 0.95, "pass_2_strong"
            if score >= 98:
                return br, 0.95, "pass_2_strong"

    # Pass 3: Medium fuzzy (name>=90 + date)
    if claim_name and claim_date:
        date_cands = billing_by_date.get(claim_date, [])
        best_br, best_combined = None, -1
        for br in date_cands:
            score = _best_name_score(claim_name, br, billing_norm_names)
            if score < 90:
                continue
            mod = 200 if _modality_matches(claim_modality, br.modality) else 0
            dx = 150 * diagnosis_modality_score(claim_diagnosis_codes, br.modality)
            combined = mod + dx + score
            if combined > best_combined:
                best_br, best_combined = br, combined
        if best_br:
            return best_br, 0.85, "pass_3_medium"

    # Pass 3b: Weak same-day (name>=70 + exact date) — catches the gap
    # between Pass 3 (>=90) and Pass 4 (±3 days). Without this, names
    # scoring 70-89 on the exact service date fall through to Pass 5+.
    if claim_name and claim_date:
        date_cands = billing_by_date.get(claim_date, [])
        best_br, best_combined = None, -1
        for br in date_cands:
            score = _best_name_score(claim_name, br, billing_norm_names)
            if score < 70:
                continue
            mod = 200 if _modality_matches(claim_modality, br.modality) else 0
            dx = 150 * diagnosis_modality_score(claim_diagnosis_codes, br.modality)
            combined = mod + dx + score
            if combined > best_combined:
                best_br, best_combined = br, combined
        if best_br:
            return best_br, 0.75, "pass_3b_weak_sameday"

    # Passes 4-4d: Date window matching (offset days, excludes same-day already handled)
    _date_passes = [
        ("pass_4_weak",            range(-3, 4),      0,  0.70),
        ("pass_4b_wider_date",     range(-7, 8),      3,  0.60),
        ("pass_4c_wide_date",      range(-14, 15),    7,  0.55),
        ("pass_4d_very_wide_date", range(-30, 31),   14,  0.50),
    ]
    if claim_name and claim_date:
        for pass_name, offset_range, skip_within, base_conf in _date_passes:
            best_br, best_combined = None, -1
            for offset in offset_range:
                if -skip_within <= offset <= skip_within:
                    continue
                check_date = claim_date + timedelta(days=offset)
                for br in billing_by_date.get(check_date, []):
                    score = _best_name_score(claim_name, br, billing_norm_names)
                    if score < 70:
                        continue
                    mod = 200 if _modality_matches(claim_modality, br.modality) else 0
                    dx = 150 * diagnosis_modality_score(claim_diagnosis_codes, br.modality)
                    combined = mod + dx + score
                    if combined > best_combined:
                        best_br, best_combined = br, combined
            if best_br:
                return best_br, base_conf, pass_name

    # Pass 5: Amount-anchored (carrier + date + billed amount)
    if claim_date and era_payment and era_payment.payer_name:
        payer_upper = era_payment.payer_name.upper()
        for br in billing_by_date.get(claim_date, []):
            if not br.insurance_carrier:
                continue
            carrier_score = fuzz.token_sort_ratio(br.insurance_carrier.upper(), payer_upper)
            if carrier_score < 60:
                continue
            if claim_billed and claim_billed > 0 and br.total_payment:
                if abs(float(br.total_payment) - claim_billed) < 0.01:
                    return br, 0.75, "pass_5_amount"
            if claim_paid and claim_paid > 0 and br.total_payment:
                if abs(float(br.total_payment) - claim_paid) < 0.01:
                    return br, 0.75, "pass_5_amount"
            if float(br.total_payment or 0) == 0 and claim_modality:
                if br.modality and claim_modality.upper() == br.modality.upper():
                    return br, 0.68, "pass_5_amount"

    # Pass 6: Name + modality (no date required)
    if claim_name and claim_modality:
        mod_key = (claim_name, claim_modality.upper())
        candidates = billing_by_modality_name.get(mod_key, [])
        if len(candidates) == 1:
            return candidates[0], 0.62, "pass_6_name_modality"
        if candidates and claim_date:
            for br in candidates:
                if br.service_date == claim_date:
                    return br, 0.65, "pass_6_name_modality"
        if not candidates and claim_modality:
            for name_key, brs in billing_by_modality_name.items():
                if name_key[1] != claim_modality.upper():
                    continue
                score = _name_score_pair(claim_name, name_key[0])
                if score >= 70 and len(brs) == 1:
                    return brs[0], 0.58, "pass_6_name_modality"

    # Pass 7: Name + amount (no date required)
    if claim_name and claim_paid and claim_paid > 0:
        candidates = billing_by_name.get(claim_name, [])
        for br in candidates:
            if br.total_payment and abs(float(br.total_payment) - claim_paid) < 0.01:
                return br, 0.65, "pass_7_name_amount"
        if claim_billed and claim_billed > 0:
            for br in candidates:
                if br.total_payment and abs(float(br.total_payment) - claim_billed) < 0.01:
                    return br, 0.62, "pass_7_name_amount"
        if not candidates:
            for name_key, brs in billing_by_name.items():
                score = _name_score_pair(claim_name, name_key)
                if score >= 70:
                    for br in brs:
                        if br.total_payment and claim_paid and abs(float(br.total_payment) - claim_paid) < 0.01:
                            return br, 0.60, "pass_7_name_amount"

    # Pass 8: Name only (no date required)
    if claim_name:
        candidates = billing_by_name.get(claim_name, [])
        if len(candidates) == 1:
            return candidates[0], 0.55, "pass_8_name_only"
        if len(candidates) > 1 and claim_date:
            closest = min(candidates,
                          key=lambda br: abs((br.service_date - claim_date).days) if br.service_date else 9999)
            if closest.service_date:
                gap = abs((closest.service_date - claim_date).days)
                if gap <= 30:
                    return closest, 0.50, "pass_8_name_only"
        if len(candidates) > 1 and not claim_date:
            unlinked = [br for br in candidates if not br.era_claim_id]
            if len(unlinked) == 1:
                return unlinked[0], 0.48, "pass_8_name_only"
        if not candidates:
            for name_key, brs in billing_by_name.items():
                score = _name_score_pair(claim_name, name_key)
                if score >= 70 and len(brs) == 1:
                    return brs[0], 0.50, "pass_8_name_only"

    # Pass 9: Broad fuzzy scan (name>=70 across ALL billing records)
    if claim_name and billing_records_list:
        best_br = None
        best_score = 0
        best_date_gap = 9999
        for br in billing_records_list:
            score = _best_name_score(claim_name, br, billing_norm_names)
            if score < 70:
                continue
            date_gap = abs((br.service_date - claim_date).days) if (claim_date and br.service_date) else 9999
            if score > best_score or (score == best_score and date_gap < best_date_gap):
                best_score = score
                best_br = br
                best_date_gap = date_gap
        if best_br:
            conf = 0.45 if best_score >= 90 else 0.40
            return best_br, conf, "pass_9_broad_fuzzy"

    return None, 0, None


# ── Match Runner ─────────────────────────────────────────────────

def run_matching(auto_accept_threshold=None, review_threshold=None, date_window_days=None, force=False):
    """Run 14-pass auto-match on all unmatched ERA claim lines.

    Args:
        force: If True, clear all existing matches first and re-run from scratch.
    """
    if force:
        EraClaimLine.query.filter(
            EraClaimLine.matched_billing_id.isnot(None)
        ).update({
            EraClaimLine.matched_billing_id: None,
            EraClaimLine.match_confidence: None,
        }, synchronize_session="fetch")
        db.session.flush()

    unmatched = EraClaimLine.query.filter(
        EraClaimLine.matched_billing_id.is_(None)
    ).all()

    if not unmatched:
        return {"status": "no_unmatched_claims", "total": 0, "matched_total": 0, "match_rate": 0}

    billing_records = BillingRecord.query.all()

    if not billing_records:
        return {"status": "no_billing_records", "total": len(unmatched), "matched_total": 0, "match_rate": 0}

    # Build indexes (NOT mutable — many-to-one)
    billing_by_name_date = defaultdict(list)
    billing_by_topaz_id = defaultdict(list)
    billing_by_patient_id = defaultdict(list)
    billing_by_date = defaultdict(list)
    billing_by_name = defaultdict(list)
    billing_by_modality_name = defaultdict(list)
    billing_norm_names = {}

    for br in billing_records:
        norm = normalize_name(br.patient_name)
        billing_norm_names[br.id] = norm
        billing_by_name_date[(norm, br.service_date)].append(br)
        billing_by_date[br.service_date].append(br)
        billing_by_name[norm].append(br)
        # Topaz ID index
        topaz_id = getattr(br, "topaz_patient_id", None)
        if topaz_id:
            for variant in _all_topaz_variants(topaz_id):
                if br not in billing_by_topaz_id[variant]:
                    billing_by_topaz_id[variant].append(br)
        # Also index by era_claim_id for previously-matched records
        if br.era_claim_id and not topaz_id:
            for variant in _all_topaz_variants(br.era_claim_id):
                if br not in billing_by_topaz_id[variant]:
                    billing_by_topaz_id[variant].append(br)
        if br.patient_id is not None:
            billing_by_patient_id[br.patient_id].append(br)
        if br.modality:
            billing_by_modality_name[(norm, br.modality.upper())].append(br)

    # Load ERA payments for payer name lookup
    payment_ids = {c.era_payment_id for c in unmatched}
    payments = EraPayment.query.filter(EraPayment.id.in_(payment_ids)).all()
    payments_by_id = {p.id: p for p in payments}

    stats = {
        "pass_0_topaz_id": 0, "pass_0b_patient_id": 0,
        "pass_1_exact": 0, "pass_2_strong": 0,
        "pass_3_medium": 0, "pass_3b_weak_sameday": 0,
        "pass_4_weak": 0, "pass_4b_wider_date": 0,
        "pass_4c_wide_date": 0, "pass_4d_very_wide_date": 0,
        "pass_5_amount": 0, "pass_6_name_modality": 0,
        "pass_7_name_amount": 0, "pass_8_name_only": 0,
        "pass_9_broad_fuzzy": 0,
        "unmatched": 0, "total": len(unmatched),
        "total_processed": len(unmatched),
    }

    for i, claim in enumerate(unmatched):
        claim_name = normalize_name(claim.patient_name_835)
        claim_date = claim.service_date_835
        claim_paid = round(float(claim.paid_amount), 2) if claim.paid_amount else None
        claim_billed = round(float(claim.billed_amount), 2) if claim.billed_amount else None
        claim_cpt = claim.cpt_code
        claim_modality = CPT_TO_MODALITY.get(claim_cpt) if claim_cpt else None
        claim_dx = getattr(claim, 'diagnosis_codes', None)
        era_payment = payments_by_id.get(claim.era_payment_id)

        matched_br, confidence, pass_name = _match_single_claim(
            claim, claim_name, claim_date, claim_paid, claim_billed,
            claim_cpt, claim_modality, era_payment,
            billing_by_name_date, billing_by_date, billing_by_topaz_id,
            billing_by_patient_id, billing_norm_names,
            billing_by_name, billing_by_modality_name,
            billing_records_list=billing_records,
            claim_diagnosis_codes=claim_dx,
        )

        if matched_br:
            stats[pass_name] += 1
            claim.matched_billing_id = matched_br.id
            claim.match_confidence = confidence

            # Store first claim_id as back-reference
            if not matched_br.era_claim_id:
                matched_br.era_claim_id = claim.claim_id

            # Auto-populate topaz_id on high-confidence matches (>=0.85)
            topaz_attr = "topaz_patient_id"
            if not getattr(matched_br, topaz_attr, None) and claim.claim_id and confidence >= 0.85:
                try:
                    base_id, _ = _decode_topaz_id(claim.claim_id)
                    if base_id and int(base_id) > 0:
                        setattr(matched_br, topaz_attr, claim.claim_id.strip())
                        for variant in _all_topaz_variants(claim.claim_id.strip()):
                            if matched_br not in billing_by_topaz_id[variant]:
                                billing_by_topaz_id[variant].append(matched_br)
                except (ValueError, TypeError):
                    pass

            # Denial status — only set denial, never clear it from auto-match.
            # In many-to-one matching, a paid secondary claim shouldn't clear
            # a denial set by the primary. Clearing requires manual resolution.
            status = CLAIM_STATUS_MAP.get(claim.claim_status)
            if status and status in DENIAL_STATUSES:
                matched_br.denial_status = status
            if claim.cas_reason_code and status in DENIAL_STATUSES:
                matched_br.denial_reason_code = claim.cas_reason_code

            # Flow-back ERA data — only set total_payment if billing record
            # has no payment AND the ERA claim actually paid something positive.
            # Don't overwrite intentional $0 (denied claims, write-offs).
            if (float(matched_br.total_payment or 0) == 0
                    and claim.paid_amount
                    and float(claim.paid_amount) > 0
                    and not matched_br.denial_status):
                matched_br.total_payment = claim.paid_amount
            if claim.cpt_code and not getattr(matched_br, "cpt_code", None):
                matched_br.cpt_code = claim.cpt_code
            if claim.paid_amount is not None and getattr(matched_br, "era_paid_amount", None) is None:
                matched_br.era_paid_amount = claim.paid_amount
            if claim.billed_amount is not None and (not getattr(matched_br, "billed_amount", None) or matched_br.billed_amount == 0):
                matched_br.billed_amount = claim.billed_amount
            if era_payment and era_payment.payment_method and not getattr(matched_br, "payment_method", None):
                try:
                    from app.revenue.underpayment_detector import normalize_payment_method
                    matched_br.payment_method = normalize_payment_method(era_payment.payment_method)
                except Exception:
                    pass
        else:
            stats["unmatched"] += 1

        # Periodic flush
        if (i + 1) % BATCH_SIZE == 0:
            db.session.flush()

    db.session.flush()

    # --- Pass S: Supply/drug linking ---
    stats["pass_s_supply_linked"] = 0
    supply_unmatched = EraClaimLine.query.filter(
        EraClaimLine.matched_billing_id.is_(None)
    ).all()
    supply_candidates = [c for c in supply_unmatched if _is_supply_code(c.cpt_code)]

    if supply_candidates:
        s_payment_ids = {c.era_payment_id for c in supply_candidates}
        siblings = EraClaimLine.query.filter(
            EraClaimLine.era_payment_id.in_(s_payment_ids),
            EraClaimLine.matched_billing_id.isnot(None),
        ).all()
        sibling_matches = {}
        for sib in siblings:
            sib_name = normalize_name(sib.patient_name_835) if sib.patient_name_835 else ""
            sib_date = sib.service_date_835
            sibling_matches[(sib.era_payment_id, sib_name, sib_date)] = sib.matched_billing_id
            key_nodate = (sib.era_payment_id, sib_name, None)
            if key_nodate not in sibling_matches:
                sibling_matches[key_nodate] = sib.matched_billing_id

        for sc in supply_candidates:
            sc_name = normalize_name(sc.patient_name_835) if sc.patient_name_835 else ""
            matched_id = sibling_matches.get((sc.era_payment_id, sc_name, sc.service_date_835))
            if not matched_id:
                matched_id = sibling_matches.get((sc.era_payment_id, sc_name, None))
            if matched_id:
                sc.matched_billing_id = matched_id
                sc.match_confidence = 0.95
                stats["pass_s_supply_linked"] += 1

    # --- Pass 10: Auto-create stub billing records ---
    still_unmatched = EraClaimLine.query.filter(
        EraClaimLine.matched_billing_id.is_(None),
        EraClaimLine.patient_name_835.isnot(None),
        EraClaimLine.claim_id.isnot(None),
    ).all()
    stats["pass_10_auto_created"] = 0

    if still_unmatched:
        stub_pids = {c.era_payment_id for c in still_unmatched}
        stub_payments = {p.id: p for p in EraPayment.query.filter(EraPayment.id.in_(stub_pids)).all()}

        for sc in still_unmatched:
            era_pay = stub_payments.get(sc.era_payment_id)
            cpt = sc.cpt_code
            modality = CPT_TO_MODALITY.get(cpt, "UNKNOWN") if cpt else "UNKNOWN"

            svc_date = sc.service_date_835
            if not svc_date and era_pay and era_pay.payment_date:
                svc_date = era_pay.payment_date
            if not svc_date:
                svc_date = date.today()

            raw_claim_id = sc.claim_id.strip()
            paid = float(sc.paid_amount) if sc.paid_amount else 0
            status_label = CLAIM_STATUS_MAP.get(sc.claim_status)

            carrier = "UNKNOWN"
            if era_pay and era_pay.payer_name:
                try:
                    from app.import_engine.carrier_normalization import normalize_era_payer
                    carrier = normalize_era_payer(era_pay.payer_name)
                except Exception:
                    carrier = era_pay.payer_name

            stub_br = BillingRecord(
                patient_name=sc.patient_name_835,
                referring_doctor="UNKNOWN",
                scan_type=cpt or "UNKNOWN",
                gado_used=False,
                insurance_carrier=carrier,
                modality=modality,
                service_date=svc_date,
                total_payment=paid,
                primary_payment=paid if status_label in ("PAID_PRIMARY", None) else 0,
                secondary_payment=paid if status_label == "PAID_SECONDARY" else 0,
                topaz_patient_id=raw_claim_id,
                era_claim_id=raw_claim_id,
                import_source="ERA_AUTO",
                denial_status=status_label if status_label in DENIAL_STATUSES else None,
                denial_reason_code=sc.cas_reason_code if status_label in DENIAL_STATUSES else None,
            )
            db.session.add(stub_br)
            db.session.flush()

            sc.matched_billing_id = stub_br.id
            sc.match_confidence = 1.0
            stats["pass_10_auto_created"] += 1

    db.session.commit()

    # Compute final unmatched count from DB (avoids negative counter bugs)
    final_unmatched = EraClaimLine.query.filter(
        EraClaimLine.matched_billing_id.is_(None)
    ).count()
    stats["unmatched"] = final_unmatched
    stats["matched_total"] = stats["total"] - stats["unmatched"]
    stats["match_rate"] = round(
        (stats["matched_total"] / stats["total"] * 100) if stats["total"] > 0 else 0, 1
    )
    # Backwards compat fields
    stats["auto_accepted"] = stats["matched_total"]
    stats["needs_review"] = 0
    stats["rejected"] = stats["unmatched"]

    logger.info(
        f"Auto-match: {stats['matched_total']}/{stats['total']} ({stats['match_rate']}%) "
        f"P0:{stats['pass_0_topaz_id']} P0b:{stats['pass_0b_patient_id']} "
        f"P1:{stats['pass_1_exact']} P2:{stats['pass_2_strong']} "
        f"P3:{stats['pass_3_medium']} P4:{stats['pass_4_weak']} P4b:{stats['pass_4b_wider_date']} "
        f"P4c:{stats['pass_4c_wide_date']} P4d:{stats['pass_4d_very_wide_date']} "
        f"P5:{stats['pass_5_amount']} P6:{stats['pass_6_name_modality']} "
        f"P7:{stats['pass_7_name_amount']} P8:{stats['pass_8_name_only']} "
        f"P9:{stats['pass_9_broad_fuzzy']} PS:{stats['pass_s_supply_linked']} "
        f"P10:{stats['pass_10_auto_created']}"
    )
    return stats


# ── Confirm / Reject / Results ───────────────────────────────────

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
    """Reject a match -- clear the matched billing ID."""
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
    """Get match results with optional status filter."""
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


# ── ERA Payment Flow-Back ────────────────────────────────────────

def _flow_back_era_payment(claim, billing_id):
    """Flow ERA payment data back to the matched billing record."""
    try:
        billing = db.session.get(BillingRecord, billing_id) if billing_id else None
        if not billing or not claim:
            return

        if claim.paid_amount is not None:
            billing.era_paid_amount = claim.paid_amount
        if claim.cas_adjustment_amount is not None:
            billing.adjustment_amount = claim.cas_adjustment_amount

        era_payment = None
        if claim.era_payment_id:
            era_payment = db.session.get(EraPayment, claim.era_payment_id)
            if era_payment and era_payment.payment_method:
                from app.revenue.underpayment_detector import normalize_payment_method
                billing.payment_method = normalize_payment_method(era_payment.payment_method)

        if claim.billed_amount and (not billing.billed_amount or billing.billed_amount == 0):
            billing.billed_amount = claim.billed_amount
        if claim.cpt_code and not billing.cpt_code:
            billing.cpt_code = claim.cpt_code
        if not billing.charge_category:
            from app.revenue.underpayment_detector import infer_charge_category
            billing.charge_category = infer_charge_category(billing)

        try:
            from app.models import PaymentDetail
            detail = PaymentDetail(
                billing_record_id=billing_id,
                era_claim_line_id=claim.id,
                payment_type='PRIMARY',
                payment_method=billing.payment_method,
                payment_amount=claim.paid_amount or 0.0,
                payer_name=era_payment.payer_name if era_payment else None,
                payment_date=era_payment.payment_date if era_payment else None,
                source='ERA_835',
            )
            db.session.add(detail)
        except Exception:
            pass
    except Exception:
        pass


# ── Smart Matching Helpers ───────────────────────────────────────

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
        pass


def _maybe_recalibrate():
    """Trigger Platt scaling recalibration if enough outcomes exist."""
    try:
        from app.matching.calibration import train_calibration
        train_calibration()
    except Exception:
        pass
