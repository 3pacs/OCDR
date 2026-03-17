"""
Auto-Matching Engine — 13 passes.

Matches ERA claim lines (from 835 files) to billing records using
progressively looser matching criteria:

  Pass 0:  Topaz ID       (claim_id == topaz_id crosswalk)            → 99%
  Pass 0b: Claim ID → patient_id (chart number cross-reference)       → 92%
  Pass 1:  Exact composite (name + service_date + amount)             → 99%
  Pass 2:  Strong fuzzy   (name>=95 + service_date + CPT/modality)    → 95%
  Pass 3:  Medium fuzzy   (name>=90 + service_date)                   → 85%
  Pass 4:  Weak fuzzy     (name>=85 + service_date ±3 days)           → 70%
  Pass 4b: Wider date     (name>=85 + service_date ±7 days)           → 60%
  Pass 4c: Wide date      (name>=90 + service_date ±14 days)          → 55%
  Pass 4d: Very wide date (name>=95 + service_date ±30 days)          → 50%
  Pass 5:  Amount-anchor  (carrier + service_date + billed amount)    → 75%
  Pass 6:  Name + modality (no date required, name>=90 + modality)    → 62%
  Pass 7:  Name + amount  (no date required, name>=90 + billed amt)   → 65%
  Pass 8:  Name only      (no date required, name>=95, multi-record)  → 55%

Many-to-one: Multiple ERA claims can link to the same billing record
(original payment, adjustments, secondary payers, appeals). Billing
records are NOT removed from indexes after first match. The first
matched claim_id is stored in BillingRecord.era_claim_id; all claims
point back via ERAClaimLine.matched_billing_id.

TOPAZ PREFIX ENCODING (critical for ID matching):
  Topaz encodes billing context as a numeric prefix on PatientID:
    No prefix:  Direct patient reference (raw PatientID)
    10000000+:  Primary insurance billing
    20000000+:  Secondary insurance billing
    30000000+:  Tertiary insurance billing
    70000000+:  Patient copay/responsibility
    80000000+:  Additional tiers
    90000000+:  Additional tiers
  To extract the real PatientID: claim_id % 10000000 (MOD 10M)
  This prefix system is used in tbl_Charges and tbl_Payments in the
  Topaz Access database, and flows into ERA 835 claim_id fields.

After matching, updates:
  - ERAClaimLine.matched_billing_id and match_confidence
  - BillingRecord.era_claim_id, denial_status, denial_reason_code
"""

import asyncio
import logging
from collections import defaultdict
from datetime import timedelta

from rapidfuzz import fuzz
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAClaimLine, ERAPayment

logger = logging.getLogger(__name__)

# Batch size for periodic commits / event-loop yields
BATCH_SIZE = 200


def _normalize_name(name: str | None) -> str:
    """Normalize patient name for matching: uppercase, strip commas, remove middle initials, sort tokens.

    Sorting tokens ensures order-independent matching so "KINLEY SHARON" and
    "SHARON KINLEY" produce the same normalized key for dictionary lookups.
    """
    if not name:
        return ""
    # Strip all commas so "SMITH, JOHN" and "SMITH JOHN" normalize identically
    cleaned = name.upper().strip().replace(",", " ")
    parts = cleaned.split()
    # Remove single-character tokens (middle initials)
    parts = [p for p in parts if len(p) > 1]
    # Sort tokens for order-independent comparison (LAST FIRST == FIRST LAST)
    parts.sort()
    return " ".join(parts).strip()


def _names_match(name1: str, name2: str, threshold: int = 85) -> tuple[bool, float]:
    """Compare two names using token_sort_ratio. Returns (match, score)."""
    n1 = _normalize_name(name1)
    n2 = _normalize_name(name2)
    if not n1 or not n2:
        return False, 0
    score = fuzz.token_sort_ratio(n1, n2)
    return score >= threshold, score


CPT_TO_MODALITY = {
    "74177": "CT", "74178": "CT", "74176": "CT", "72193": "CT",
    "72192": "CT", "72194": "CT", "74174": "CT",
    "70553": "HMRI", "70551": "HMRI", "70552": "HMRI",
    "72141": "HMRI", "72148": "HMRI", "72156": "HMRI",
    "73721": "HMRI", "73718": "HMRI", "73220": "HMRI", "77084": "HMRI",
    "78816": "PET", "78815": "PET", "78814": "PET",
    "78811": "PET", "78812": "PET", "78813": "PET",
    "78300": "BONE", "78305": "BONE", "78306": "BONE",
    "71046": "DX", "71045": "DX", "73030": "DX",
}

CLAIM_STATUS_MAP = {
    "1": "PAID_PRIMARY",
    "2": "PAID_SECONDARY",
    "3": "PAID_TERTIARY",
    "4": "DENIED",
    "5": "PENDING",
    "10": "PENDING",
    "13": "PENDING",
    "19": "PAID_PRIMARY",
    "20": "PAID_SECONDARY",
    "22": "REVERSAL",
}


def _strip_leading_zeros(s: str) -> str:
    """Strip leading zeros from numeric-looking strings for ID comparison."""
    stripped = s.lstrip("0")
    return stripped or "0"


# Topaz billing context prefixes (multiples of 10,000,000)
TOPAZ_PREFIX_MOD = 10_000_000
TOPAZ_PREFIX_LABELS = {
    0: "direct",
    1: "primary",
    2: "secondary",
    3: "tertiary",
    7: "copay",
    8: "tier_8",
    9: "tier_9",
}


def _decode_topaz_id(raw_id: str) -> tuple[str, str]:
    """Decode a Topaz prefixed PatientID.

    Topaz encodes billing context as numeric prefix:
      10061723 → patient 61723, primary insurance
      20061723 → patient 61723, secondary insurance
      70061723 → patient 61723, patient copay
      61723    → patient 61723, direct reference

    Returns (base_patient_id_str, billing_context).
    """
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
    else:
        return str(num), "direct"


def _all_topaz_variants(raw_id: str) -> list[str]:
    """Generate all possible lookup keys for a Topaz ID.

    Given "10061723", returns ["10061723", "61723"] (raw + decoded).
    Given "00061501", returns ["00061501", "61501"] (raw + zero-stripped).
    Given "61723", returns ["61723"] (already base).
    """
    keys = set()
    cleaned = raw_id.strip()
    keys.add(cleaned)

    # Strip leading zeros
    stripped = _strip_leading_zeros(cleaned)
    keys.add(stripped)

    # Decode Topaz prefix (MOD 10M)
    base_id, _ = _decode_topaz_id(cleaned)
    keys.add(base_id)

    # Also strip leading zeros from decoded base
    keys.add(_strip_leading_zeros(base_id))

    keys.discard("")
    return list(keys)


def _best_name_score(claim_name, br, billing_norm_names, billing_display_names):
    """Get the best fuzzy name score across patient_name and patient_name_display."""
    norm = billing_norm_names.get(br.id, "")
    score1 = fuzz.token_sort_ratio(claim_name, norm) if norm else 0
    display = billing_display_names.get(br.id, "")
    score2 = fuzz.token_sort_ratio(claim_name, display) if display else 0
    return max(score1, score2)


def _match_single_claim(
    claim,
    claim_name,
    claim_date,
    claim_paid,
    claim_billed,
    claim_cpt,
    claim_modality,
    era_payment,
    billing_by_name_date,
    billing_by_date,
    billing_by_topaz_id,
    billing_by_patient_id,
    billing_norm_names,
    billing_display_names,
    billing_by_name,
    billing_by_modality_name,
):
    """Run matching passes for a single claim.

    Returns (billing_record, confidence, pass_name) or (None, 0, None).
    """

    # Pass 0: Topaz ID crosswalk match (with name corroboration)
    # Handles Topaz prefix encoding: 10061723 (primary) → base 61723
    if claim.claim_id:
        topaz_key = claim.claim_id.strip()
        candidates = []
        # Try all variants: raw, zero-stripped, prefix-decoded
        for variant in _all_topaz_variants(topaz_key):
            candidates = billing_by_topaz_id.get(variant, [])
            if candidates:
                break
        if candidates and claim_name:
            best_br = None
            best_score = 0
            for c in candidates:
                name_score = _best_name_score(claim_name, c, billing_norm_names, billing_display_names)
                date_match = (c.service_date == claim_date) if claim_date else False
                combined = name_score + (10 if date_match else 0)
                if combined > best_score:
                    best_score = combined
                    best_br = c
            # Accept if name is at least loosely similar (>=60) or date+name combined
            if best_br and best_score >= 60:
                return best_br, 0.99, "pass_0_topaz_id"
        elif candidates and not claim_name:
            # No name on the claim — accept best date match or first candidate
            if claim_date:
                for c in candidates:
                    if c.service_date == claim_date:
                        return c, 0.92, "pass_0_topaz_id"
            # Fall back to first candidate at lower confidence
            return candidates[0], 0.85, "pass_0_topaz_id"

    # Pass 0b: Claim ID → patient_id (chart number) cross-reference
    # ERA claim_id might be or contain the chart number, with or without prefix
    if claim.claim_id:
        claim_id_stripped = claim.claim_id.strip()
        # Try all variants: raw, zero-stripped, prefix-decoded
        p0b_candidates = []
        for variant in _all_topaz_variants(claim_id_stripped):
            try:
                variant_int = int(variant)
                p0b_candidates = billing_by_patient_id.get(variant_int, [])
                if p0b_candidates:
                    break
            except (ValueError, OverflowError):
                continue
        if p0b_candidates and claim_name:
            best_br = None
            best_score = 0
            for c in p0b_candidates:
                name_score = _best_name_score(claim_name, c, billing_norm_names, billing_display_names)
                date_match = (c.service_date == claim_date) if claim_date else False
                combined = name_score + (10 if date_match else 0)
                if combined > best_score:
                    best_score = combined
                    best_br = c
            if best_br and best_score >= 70:
                return best_br, 0.92, "pass_0b_patient_id"
        elif p0b_candidates and claim_date:
            for c in p0b_candidates:
                if c.service_date == claim_date:
                    return c, 0.88, "pass_0b_patient_id"

    # Pass 1: Exact composite (name + date + amount)
    if claim_name and claim_date:
        key = (claim_name, claim_date)
        candidates = billing_by_name_date.get(key, [])
        if len(candidates) == 1:
            return candidates[0], 0.99, "pass_1_exact"
        # Multiple candidates — use amount to disambiguate
        for br in candidates:
            if claim_paid and br.total_payment:
                if abs(float(br.total_payment) - claim_paid) < 0.01:
                    return br, 0.99, "pass_1_exact"
        # Multiple candidates, no amount match — take first (same name+date)
        if candidates:
            return candidates[0], 0.95, "pass_1_exact"

    # Pass 2: Strong fuzzy (name>=95 + date + CPT/modality)
    if claim_name and claim_date:
        date_candidates = billing_by_date.get(claim_date, [])
        for br in date_candidates:
            score = _best_name_score(claim_name, br, billing_norm_names, billing_display_names)
            if score < 95:
                continue
            if claim_modality and br.modality and claim_modality.upper() == br.modality.upper():
                return br, 0.95, "pass_2_strong"
            if score >= 98:
                return br, 0.95, "pass_2_strong"

    # Pass 3: Medium fuzzy (name>=90 + date)
    if claim_name and claim_date:
        for br in billing_by_date.get(claim_date, []):
            score = _best_name_score(claim_name, br, billing_norm_names, billing_display_names)
            if score >= 90:
                return br, 0.85, "pass_3_medium"

    # Pass 4: Weak fuzzy (name>=85 + date ±3 days)
    if claim_name and claim_date:
        for offset in range(-3, 4):
            if offset == 0:
                continue  # Already checked in Pass 3
            check_date = claim_date + timedelta(days=offset)
            for br in billing_by_date.get(check_date, []):
                score = _best_name_score(claim_name, br, billing_norm_names, billing_display_names)
                if score >= 85:
                    return br, 0.70, "pass_4_weak"

    # Pass 4b: Wider date window (name>=85 + date ±7 days)
    if claim_name and claim_date:
        for offset in range(-7, 8):
            if -3 <= offset <= 3:
                continue  # Already checked
            check_date = claim_date + timedelta(days=offset)
            for br in billing_by_date.get(check_date, []):
                score = _best_name_score(claim_name, br, billing_norm_names, billing_display_names)
                if score >= 85:
                    return br, 0.60, "pass_4b_wider_date"

    # Pass 4c: Wide date window (name>=90 + date ±14 days)
    if claim_name and claim_date:
        for offset in range(-14, 15):
            if -7 <= offset <= 7:
                continue  # Already checked
            check_date = claim_date + timedelta(days=offset)
            for br in billing_by_date.get(check_date, []):
                score = _best_name_score(claim_name, br, billing_norm_names, billing_display_names)
                if score >= 90:
                    return br, 0.55, "pass_4c_wide_date"

    # Pass 4d: Very wide date window (name>=95 + date ±30 days)
    if claim_name and claim_date:
        for offset in range(-30, 31):
            if -14 <= offset <= 14:
                continue  # Already checked
            check_date = claim_date + timedelta(days=offset)
            for br in billing_by_date.get(check_date, []):
                score = _best_name_score(claim_name, br, billing_norm_names, billing_display_names)
                if score >= 95:
                    return br, 0.50, "pass_4d_very_wide_date"

    # Pass 5: Amount-anchored (carrier + date + billed amount)
    # Uses billed_amount from ERA (not paid), because billing total_payment
    # is often $0 before matching. Also tries paid_amount as fallback.
    if claim_date and era_payment and era_payment.payer_name:
        payer_upper = era_payment.payer_name.upper()
        for br in billing_by_date.get(claim_date, []):
            if not br.insurance_carrier:
                continue
            carrier_score = fuzz.token_sort_ratio(br.insurance_carrier.upper(), payer_upper)
            if carrier_score < 60:
                continue
            # Try matching billed amount against billing total_payment
            if claim_billed and claim_billed > 0 and br.total_payment:
                if abs(float(br.total_payment) - claim_billed) < 0.01:
                    return br, 0.75, "pass_5_amount"
            # Try paid amount
            if claim_paid and claim_paid > 0 and br.total_payment:
                if abs(float(br.total_payment) - claim_paid) < 0.01:
                    return br, 0.75, "pass_5_amount"
            # If billing has $0 but carrier and date match, use modality as tie-breaker
            if float(br.total_payment or 0) == 0 and claim_modality:
                if br.modality and claim_modality.upper() == br.modality.upper():
                    return br, 0.68, "pass_5_amount"

    # Pass 6: Name + modality (NO date required) — for claims missing service_date
    if claim_name and claim_modality:
        mod_key = (claim_name, claim_modality.upper())
        candidates = billing_by_modality_name.get(mod_key, [])
        if len(candidates) == 1:
            return candidates[0], 0.62, "pass_6_name_modality"
        # If multiple, try date disambiguation
        if candidates and claim_date:
            for br in candidates:
                if br.service_date == claim_date:
                    return br, 0.65, "pass_6_name_modality"
        # Also try fuzzy name match across all modality candidates
        if not candidates and claim_modality:
            for name_key, brs in billing_by_modality_name.items():
                if name_key[1] != claim_modality.upper():
                    continue
                score = fuzz.token_sort_ratio(claim_name, name_key[0])
                if score >= 90 and len(brs) == 1:
                    return brs[0], 0.58, "pass_6_name_modality"

    # Pass 7: Name + amount (NO date required) — for claims missing service_date
    if claim_name and claim_paid and claim_paid > 0:
        candidates = billing_by_name.get(claim_name, [])
        # Try exact name match + paid amount
        for br in candidates:
            if br.total_payment and abs(float(br.total_payment) - claim_paid) < 0.01:
                return br, 0.65, "pass_7_name_amount"
        # Try exact name match + billed amount
        if claim_billed and claim_billed > 0:
            for br in candidates:
                if br.total_payment and abs(float(br.total_payment) - claim_billed) < 0.01:
                    return br, 0.62, "pass_7_name_amount"
        # Also try fuzzy name (>=90) across all billing records
        if not candidates:
            for name_key, brs in billing_by_name.items():
                score = fuzz.token_sort_ratio(claim_name, name_key)
                if score >= 90:
                    for br in brs:
                        if br.total_payment and claim_paid and abs(float(br.total_payment) - claim_paid) < 0.01:
                            return br, 0.60, "pass_7_name_amount"

    # Pass 8: Name only (NO date required) — strong name match
    if claim_name:
        candidates = billing_by_name.get(claim_name, [])
        if len(candidates) == 1:
            return candidates[0], 0.55, "pass_8_name_only"
        # For multi-record patients: if claim has date, pick closest date
        if len(candidates) > 1 and claim_date:
            closest = min(candidates, key=lambda br: abs((br.service_date - claim_date).days) if br.service_date else 9999)
            if closest.service_date:
                gap = abs((closest.service_date - claim_date).days)
                if gap <= 30:
                    return closest, 0.50, "pass_8_name_only"
        # For multi-record patients without date: pick most recent unmatched
        if len(candidates) > 1 and not claim_date:
            # Pick the one with no era_claim_id yet (unmatched)
            unlinked = [br for br in candidates if not br.era_claim_id]
            if len(unlinked) == 1:
                return unlinked[0], 0.48, "pass_8_name_only"

        # Also try fuzzy name across all normalized names
        if not candidates:
            for name_key, brs in billing_by_name.items():
                score = fuzz.token_sort_ratio(claim_name, name_key)
                if score >= 95 and len(brs) == 1:
                    return brs[0], 0.50, "pass_8_name_only"

    return None, 0, None


async def run_auto_match(session: AsyncSession) -> dict:
    """
    Run all matching passes on unmatched ERA claim lines.

    Allows many-to-one matching: multiple ERA claims can point to the
    same billing record (original + adjustments + secondary payers).

    Processes in batches of BATCH_SIZE with periodic commits and
    event-loop yields to prevent timeout on large datasets.
    """
    unmatched_result = await session.execute(
        select(ERAClaimLine).where(ERAClaimLine.matched_billing_id.is_(None))
    )
    unmatched_claims = list(unmatched_result.scalars().all())

    if not unmatched_claims:
        return {"status": "no_unmatched_claims", "total": 0, "matched_total": 0, "match_rate": 0}

    billing_result = await session.execute(select(BillingRecord))
    billing_records = list(billing_result.scalars().all())

    if not billing_records:
        return {"status": "no_billing_records", "total": len(unmatched_claims), "matched_total": 0, "match_rate": 0}

    # Build indexes — NOT mutable (many-to-one: billing records stay in indexes)
    billing_by_name_date = defaultdict(list)
    billing_by_topaz_id = defaultdict(list)
    billing_by_patient_id = defaultdict(list)
    billing_by_date = defaultdict(list)
    billing_by_name = defaultdict(list)  # name-only index for dateless passes
    billing_by_modality_name = defaultdict(list)  # (name, modality) index
    billing_norm_names = {}
    billing_display_names = {}
    for br in billing_records:
        norm = _normalize_name(br.patient_name)
        norm_display = _normalize_name(br.patient_name_display) if br.patient_name_display else ""
        billing_norm_names[br.id] = norm
        billing_display_names[br.id] = norm_display
        billing_by_name_date[(norm, br.service_date)].append(br)
        # Also index by display name if different
        if norm_display and norm_display != norm:
            billing_by_name_date[(norm_display, br.service_date)].append(br)
        billing_by_date[br.service_date].append(br)
        billing_by_name[norm].append(br)
        if norm_display and norm_display != norm:
            billing_by_name[norm_display].append(br)
        if br.topaz_id:
            # Index all variants: raw, zero-stripped, prefix-decoded
            for variant in _all_topaz_variants(br.topaz_id):
                if br not in billing_by_topaz_id[variant]:
                    billing_by_topaz_id[variant].append(br)
        # Also index by era_claim_id if set from previous match runs —
        # this lets Pass 0 find billing records that were matched by name/date
        # in earlier runs but never had topaz_id set via crosswalk import.
        if br.era_claim_id and not br.topaz_id:
            for variant in _all_topaz_variants(br.era_claim_id):
                if br not in billing_by_topaz_id[variant]:
                    billing_by_topaz_id[variant].append(br)
        if br.patient_id is not None:
            billing_by_patient_id[br.patient_id].append(br)
        if br.modality:
            billing_by_modality_name[(norm, br.modality.upper())].append(br)
            if norm_display and norm_display != norm:
                billing_by_modality_name[(norm_display, br.modality.upper())].append(br)

    # Load ERA payments for payer name lookup
    payment_ids = {c.era_payment_id for c in unmatched_claims}
    payment_result = await session.execute(
        select(ERAPayment).where(ERAPayment.id.in_(payment_ids))
    )
    payments_by_id = {p.id: p for p in payment_result.scalars().all()}

    # Diagnostic: count claims with missing data
    claims_no_name = sum(1 for c in unmatched_claims if not c.patient_name_835)
    claims_no_date = sum(1 for c in unmatched_claims if not c.service_date_835)
    claims_no_both = sum(1 for c in unmatched_claims if not c.patient_name_835 and not c.service_date_835)
    logger.info(
        f"Auto-match diagnostics: {len(unmatched_claims)} unmatched claims, "
        f"{len(billing_records)} billing records, "
        f"{len(billing_by_topaz_id)} unique topaz_ids in billing, "
        f"{len(billing_by_patient_id)} unique patient_ids in billing. "
        f"Claims missing: name={claims_no_name}, date={claims_no_date}, both={claims_no_both}"
    )

    stats = {
        "pass_0_topaz_id": 0,
        "pass_0b_patient_id": 0,
        "pass_1_exact": 0,
        "pass_2_strong": 0,
        "pass_3_medium": 0,
        "pass_4_weak": 0,
        "pass_4b_wider_date": 0,
        "pass_4c_wide_date": 0,
        "pass_4d_very_wide_date": 0,
        "pass_5_amount": 0,
        "pass_6_name_modality": 0,
        "pass_7_name_amount": 0,
        "pass_8_name_only": 0,
        "unmatched": 0,
        "total": len(unmatched_claims),
    }

    pending_commits = 0

    for i, claim in enumerate(unmatched_claims):
        claim_name = _normalize_name(claim.patient_name_835)
        claim_date = claim.service_date_835
        claim_paid = round(float(claim.paid_amount), 2) if claim.paid_amount else None
        claim_billed = round(float(claim.billed_amount), 2) if claim.billed_amount else None
        claim_cpt = claim.cpt_code
        claim_modality = CPT_TO_MODALITY.get(claim_cpt) if claim_cpt else None
        era_payment = payments_by_id.get(claim.era_payment_id)

        matched_br, confidence, pass_name = _match_single_claim(
            claim, claim_name, claim_date, claim_paid, claim_billed,
            claim_cpt, claim_modality,
            era_payment,
            billing_by_name_date, billing_by_date, billing_by_topaz_id,
            billing_by_patient_id,
            billing_norm_names, billing_display_names,
            billing_by_name, billing_by_modality_name,
        )

        if matched_br:
            stats[pass_name] += 1

            # Apply match — many-to-one: don't remove billing record from indexes
            claim.matched_billing_id = matched_br.id
            claim.match_confidence = confidence

            # Store first claim_id as back-reference (don't overwrite if already set)
            if not matched_br.era_claim_id:
                matched_br.era_claim_id = claim.claim_id

            # Auto-populate topaz_id on high-confidence matches (>=0.85 = passes 0b,1,2,3)
            # so subsequent claims for the same patient can use Pass 0 instantly.
            # Only sets it if the claim_id looks like a valid numeric Topaz patient ID.
            if not matched_br.topaz_id and claim.claim_id and confidence >= 0.85:
                try:
                    base_id, _ = _decode_topaz_id(claim.claim_id)
                    if base_id and int(base_id) > 0:
                        matched_br.topaz_id = claim.claim_id.strip()
                        # Also add to live index so same-batch claims benefit
                        for variant in _all_topaz_variants(matched_br.topaz_id):
                            if matched_br not in billing_by_topaz_id[variant]:
                                billing_by_topaz_id[variant].append(matched_br)
                except (ValueError, TypeError):
                    pass

            status = CLAIM_STATUS_MAP.get(claim.claim_status)
            if status:
                matched_br.denial_status = status
            if claim.cas_reason_code:
                matched_br.denial_reason_code = claim.cas_reason_code
            if float(matched_br.total_payment or 0) == 0 and claim.paid_amount:
                matched_br.total_payment = claim.paid_amount

            pending_commits += 1
        else:
            stats["unmatched"] += 1

        # Periodic flush + yield to prevent event-loop starvation and timeout
        if (i + 1) % BATCH_SIZE == 0:
            if pending_commits > 0:
                await session.flush()
                pending_commits = 0
            # Yield to event loop so HTTP timeout doesn't fire
            await asyncio.sleep(0)
            if (i + 1) % (BATCH_SIZE * 5) == 0:
                logger.info(
                    f"Auto-match progress: {i + 1}/{len(unmatched_claims)} processed"
                )

    await session.commit()

    stats["matched_total"] = stats["total"] - stats["unmatched"]
    stats["match_rate"] = round(
        (stats["matched_total"] / stats["total"] * 100) if stats["total"] > 0 else 0, 1
    )

    logger.info(
        f"Auto-match: {stats['matched_total']}/{stats['total']} ({stats['match_rate']}%) "
        f"P0:{stats['pass_0_topaz_id']} P0b:{stats['pass_0b_patient_id']} "
        f"P1:{stats['pass_1_exact']} P2:{stats['pass_2_strong']} "
        f"P3:{stats['pass_3_medium']} P4:{stats['pass_4_weak']} P4b:{stats['pass_4b_wider_date']} "
        f"P4c:{stats['pass_4c_wide_date']} P4d:{stats['pass_4d_very_wide_date']} "
        f"P5:{stats['pass_5_amount']} P6:{stats['pass_6_name_modality']} "
        f"P7:{stats['pass_7_name_amount']} P8:{stats['pass_8_name_only']}"
    )
    return stats


async def get_match_summary(session: AsyncSession) -> dict:
    """Get current matching statistics."""
    total_result = await session.execute(select(func.count(ERAClaimLine.id)))
    total = total_result.scalar() or 0

    matched_result = await session.execute(
        select(func.count(ERAClaimLine.id)).where(ERAClaimLine.matched_billing_id.is_not(None))
    )
    matched = matched_result.scalar() or 0

    tiers = {}
    for label, lo, hi in [
        ("exact_99", 0.98, 1.01),
        ("strong_95", 0.94, 0.98),
        ("medium_85", 0.84, 0.94),
        ("amount_75", 0.74, 0.84),
        ("weak_70", 0.54, 0.74),
        ("low_50", 0.44, 0.54),
    ]:
        tier_result = await session.execute(
            select(func.count(ERAClaimLine.id)).where(
                ERAClaimLine.match_confidence >= lo,
                ERAClaimLine.match_confidence < hi,
            )
        )
        tiers[label] = tier_result.scalar() or 0

    linked_billing = await session.execute(
        select(func.count(BillingRecord.id)).where(BillingRecord.era_claim_id.is_not(None))
    )

    denied = await session.execute(
        select(func.count(BillingRecord.id)).where(BillingRecord.denial_status == "DENIED")
    )

    return {
        "total_era_claims": total,
        "matched": matched,
        "unmatched": total - matched,
        "match_rate": round(matched / total * 100, 1) if total > 0 else 0,
        "by_confidence": tiers,
        "billing_records_linked": linked_billing.scalar() or 0,
        "denied_claims": denied.scalar() or 0,
    }


async def get_unmatched_claims(session: AsyncSession, page: int = 1, per_page: int = 50) -> dict:
    """Get unmatched ERA claim lines for manual review."""
    total_result = await session.execute(
        select(func.count(ERAClaimLine.id)).where(ERAClaimLine.matched_billing_id.is_(None))
    )
    total = total_result.scalar() or 0

    result = await session.execute(
        select(ERAClaimLine, ERAPayment.payer_name, ERAPayment.filename)
        .join(ERAPayment, ERAClaimLine.era_payment_id == ERAPayment.id)
        .where(ERAClaimLine.matched_billing_id.is_(None))
        .order_by(ERAClaimLine.service_date_835.desc().nullslast())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )

    items = []
    for claim, payer_name, filename in result.all():
        items.append({
            "id": claim.id,
            "claim_id": claim.claim_id,
            "patient_name": claim.patient_name_835,
            "service_date": claim.service_date_835.isoformat() if claim.service_date_835 else None,
            "cpt_code": claim.cpt_code,
            "billed_amount": float(claim.billed_amount) if claim.billed_amount else None,
            "paid_amount": float(claim.paid_amount) if claim.paid_amount else None,
            "claim_status": CLAIM_STATUS_MAP.get(claim.claim_status, claim.claim_status),
            "cas_group_code": claim.cas_group_code,
            "cas_reason_code": claim.cas_reason_code,
            "payer_name": payer_name,
            "source_file": filename,
        })

    return {"total": total, "page": page, "items": items}


async def get_matched_claims(session: AsyncSession, page: int = 1, per_page: int = 50) -> dict:
    """Get matched ERA claim lines with billing record details."""
    total_result = await session.execute(
        select(func.count(ERAClaimLine.id)).where(ERAClaimLine.matched_billing_id.is_not(None))
    )
    total = total_result.scalar() or 0

    result = await session.execute(
        select(ERAClaimLine, BillingRecord, ERAPayment.payer_name)
        .join(BillingRecord, ERAClaimLine.matched_billing_id == BillingRecord.id)
        .join(ERAPayment, ERAClaimLine.era_payment_id == ERAPayment.id)
        .where(ERAClaimLine.matched_billing_id.is_not(None))
        .order_by(ERAClaimLine.match_confidence.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )

    items = []
    for claim, billing, payer_name in result.all():
        items.append({
            "claim_id": claim.claim_id,
            "confidence": float(claim.match_confidence) if claim.match_confidence else None,
            "era_patient": claim.patient_name_835,
            "billing_patient": billing.patient_name,
            "service_date": billing.service_date.isoformat() if billing.service_date else None,
            "era_paid": float(claim.paid_amount) if claim.paid_amount else None,
            "billing_total": float(billing.total_payment) if billing.total_payment else None,
            "modality": billing.modality,
            "carrier": billing.insurance_carrier,
            "era_payer": payer_name,
            "cpt_code": claim.cpt_code,
            "status": CLAIM_STATUS_MAP.get(claim.claim_status, claim.claim_status),
        })

    return {"total": total, "page": page, "items": items}


async def diagnose_unmatched_claim(session: AsyncSession, era_claim_line_id: int) -> dict:
    """Explain WHY a specific ERA claim didn't match any billing record.

    Returns detailed diagnostics: what data the claim has, what was tried,
    the closest billing records found and why they weren't good enough.
    """
    # Load the claim
    result = await session.execute(
        select(ERAClaimLine).where(ERAClaimLine.id == era_claim_line_id)
    )
    claim = result.scalar_one_or_none()
    if not claim:
        return {"error": "ERA claim line not found"}

    # Load ERA payment for payer info
    payment = None
    if claim.era_payment_id:
        p_result = await session.execute(
            select(ERAPayment).where(ERAPayment.id == claim.era_payment_id)
        )
        payment = p_result.scalar_one_or_none()

    claim_name = _normalize_name(claim.patient_name_835)
    claim_date = claim.service_date_835
    claim_cpt = claim.cpt_code
    claim_modality = CPT_TO_MODALITY.get(claim_cpt) if claim_cpt else None

    diag = {
        "claim": {
            "id": claim.id,
            "claim_id": claim.claim_id,
            "patient_name_835": claim.patient_name_835,
            "normalized_name": claim_name,
            "service_date": claim_date.isoformat() if claim_date else None,
            "cpt_code": claim_cpt,
            "derived_modality": claim_modality,
            "billed_amount": float(claim.billed_amount) if claim.billed_amount else None,
            "paid_amount": float(claim.paid_amount) if claim.paid_amount else None,
            "payer_name": payment.payer_name if payment else None,
            "matched_billing_id": claim.matched_billing_id,
        },
        "missing_data": [],
        "pass_results": [],
        "closest_candidates": [],
    }

    if claim.matched_billing_id:
        diag["status"] = "already_matched"
        return diag

    if not claim.patient_name_835:
        diag["missing_data"].append("patient_name_835 is NULL — most passes require a name")
    if not claim.service_date_835:
        diag["missing_data"].append("service_date_835 is NULL — passes 0-5 need a date")
    if not claim.claim_id:
        diag["missing_data"].append("claim_id is NULL — Pass 0 (topaz crosswalk) disabled")

    # Load all billing records for analysis
    billing_result = await session.execute(select(BillingRecord))
    billing_records = list(billing_result.scalars().all())

    if not billing_records:
        diag["pass_results"].append("NO BILLING RECORDS IN DATABASE")
        return diag

    # --- Pass 0 diagnosis: Topaz ID (with prefix decoding) ---
    if claim.claim_id:
        topaz_key = claim.claim_id.strip()
        base_id, billing_context = _decode_topaz_id(topaz_key)
        claim_variants = set(_all_topaz_variants(topaz_key))
        topaz_matches = [br for br in billing_records
                         if br.topaz_id and set(_all_topaz_variants(br.topaz_id)) & claim_variants]
        topaz_populated = sum(1 for br in billing_records if br.topaz_id)
        diag["claim"]["decoded_base_id"] = base_id
        diag["claim"]["billing_context"] = billing_context
        if topaz_matches:
            norm_cache = {br.id: _normalize_name(br.patient_name) for br in topaz_matches}
            disp_cache = {br.id: (_normalize_name(br.patient_name_display) if br.patient_name_display else "") for br in topaz_matches}
            names_for = [(br.id, br.patient_name, _best_name_score(claim_name, br, norm_cache, disp_cache))
                         for br in topaz_matches]
            diag["pass_results"].append({
                "pass": "P0_topaz",
                "result": "TOPAZ ID FOUND but name corroboration may have failed",
                "topaz_key": topaz_key,
                "billing_matches": [{"id": n[0], "name": n[1], "name_score": n[2]} for n in names_for],
            })
        else:
            diag["pass_results"].append({
                "pass": "P0_topaz",
                "result": "NO billing record has topaz_id matching this claim_id",
                "claim_id": topaz_key,
                "topaz_id_coverage": f"{topaz_populated}/{len(billing_records)} billing records have topaz_id",
            })

    # --- Pass 0b diagnosis: claim_id as patient_id (with prefix decoding) ---
    if claim.claim_id:
        pid_matches = []
        tried_variants = []
        for variant in _all_topaz_variants(claim.claim_id.strip()):
            try:
                v_int = int(variant)
                tried_variants.append(v_int)
                matches = [br for br in billing_records if br.patient_id == v_int]
                pid_matches.extend(matches)
            except (ValueError, OverflowError):
                continue
        if pid_matches:
            diag["pass_results"].append({
                "pass": "P0b_patient_id",
                "result": f"Found {len(pid_matches)} billing records matching patient_id variants {tried_variants}",
                "records": [{"id": br.id, "name": br.patient_name,
                             "date": br.service_date.isoformat() if br.service_date else None}
                            for br in pid_matches[:5]],
            })
        else:
            diag["pass_results"].append({
                "pass": "P0b_patient_id",
                "result": f"No billing record has patient_id in {tried_variants}",
            })

    # --- Name search: find closest name matches ---
    if claim_name:
        name_scores = []
        norm_cache = {}
        for br in billing_records:
            norm = _normalize_name(br.patient_name)
            norm_cache[br.id] = norm
            score = fuzz.token_sort_ratio(claim_name, norm)
            # Also check display name
            if br.patient_name_display:
                norm_d = _normalize_name(br.patient_name_display)
                score = max(score, fuzz.token_sort_ratio(claim_name, norm_d))
            if score >= 60:
                name_scores.append((br, score))

        name_scores.sort(key=lambda x: -x[1])
        top_5 = name_scores[:5]

        if top_5:
            diag["closest_candidates"] = []
            for br, score in top_5:
                date_match = ("EXACT" if (claim_date and br.service_date == claim_date) else
                              f"off by {abs((br.service_date - claim_date).days)} days" if (claim_date and br.service_date) else
                              "no ERA date")
                diag["closest_candidates"].append({
                    "billing_id": br.id,
                    "patient_name": br.patient_name,
                    "normalized": norm_cache.get(br.id, ""),
                    "name_score": score,
                    "service_date": br.service_date.isoformat() if br.service_date else None,
                    "date_match": date_match,
                    "modality": br.modality,
                    "topaz_id": br.topaz_id,
                    "patient_id": br.patient_id,
                    "insurance": br.insurance_carrier,
                    "total_payment": float(br.total_payment or 0),
                })

            # Explain why best candidate wasn't matched
            br, score = top_5[0]
            reasons = []
            if score < 85:
                reasons.append(f"Name score {score} < 85 minimum for weakest name pass (P4)")
            elif score < 90:
                reasons.append(f"Name score {score} < 90 for medium fuzzy (P3)")
            elif score < 95:
                reasons.append(f"Name score {score} < 95 for strong fuzzy (P2)")
            if claim_date and br.service_date and claim_date != br.service_date:
                gap = abs((br.service_date - claim_date).days)
                if gap > 7:
                    reasons.append(f"Date off by {gap} days (max is ±7 for P4b)")
                elif gap > 3:
                    reasons.append(f"Date off by {gap} days — needs P4b (±7d) at 60% confidence")
            if not claim_date:
                reasons.append("No service_date on ERA claim — passes 1-5 all require date")
            if not reasons:
                reasons.append("Name and date look like they should match — possible indexing issue or duplicate key conflict")
            diag["best_candidate_reasons"] = reasons
        else:
            diag["pass_results"].append({
                "pass": "name_search",
                "result": "NO billing record has name score >= 60 for this patient",
                "claim_name_normalized": claim_name,
                "suggestion": "This patient may not be in the OCMRI billing data",
            })

    # --- Date search: how many records on that day? ---
    if claim_date:
        same_day = [br for br in billing_records if br.service_date == claim_date]
        diag["same_date_records"] = len(same_day)
        if not same_day:
            diag["pass_results"].append({
                "pass": "date_search",
                "result": f"NO billing records exist for date {claim_date.isoformat()}",
                "suggestion": "OCMRI data may not cover this date range",
            })

    diag["status"] = "unmatched"
    return diag
