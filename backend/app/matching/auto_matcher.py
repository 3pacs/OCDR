"""
8-Pass Auto-Matching Engine.

Matches ERA claim lines (from 835 files) to billing records using
progressively looser matching criteria:

  Pass 0: Topaz ID       (claim_id == topaz_id crosswalk)       → 99%
  Pass 1: Exact composite (name + service_date + amount)        → 99%
  Pass 2: Strong fuzzy   (name>=95 + service_date + CPT)        → 95%
  Pass 3: Medium fuzzy   (name>=90 + service_date + modality)   → 85%
  Pass 4: Weak fuzzy     (name>=85 + service_date ±3 days)      → 70%
  Pass 5: Amount-anchor  (carrier + service_date + amount)      → 75%
  Pass 6: Name + amount  (no date required, name>=90 + amount)  → 65%
  Pass 7: Name only      (no date required, name>=95)           → 55%

Many-to-one: Multiple ERA claims can link to the same billing record
(original payment, adjustments, secondary payers, appeals). Billing
records are NOT removed from indexes after first match. The first
matched claim_id is stored in BillingRecord.era_claim_id; all claims
point back via ERAClaimLine.matched_billing_id.

Key insight: ERA claim_id is the Topaz billing system ID. This is NOT
the same as BillingRecord.patient_id, which is the chart number from
OCMRI.xlsx. Matches found by passes 1-7 teach us the chart↔topaz
crosswalk, which Pass 0 can then exploit for faster future matching.

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
    """Normalize patient name for matching: uppercase, strip commas, remove middle initials."""
    if not name:
        return ""
    # Strip all commas so "SMITH, JOHN" and "SMITH JOHN" normalize identically
    cleaned = name.upper().strip().replace(",", " ")
    parts = cleaned.split()
    # Remove single-character tokens (middle initials)
    parts = [p for p in parts if len(p) > 1]
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


def _match_single_claim(
    claim,
    claim_name,
    claim_date,
    claim_paid,
    claim_cpt,
    claim_modality,
    era_payment,
    billing_by_name_date,
    billing_by_date,
    billing_by_topaz_id,
    billing_norm_names,
    billing_by_name,
):
    """Run 8-pass matching for a single claim. Returns (billing_record, confidence, pass_name) or (None, 0, None)."""

    # Pass 0: Topaz ID crosswalk match (with name corroboration)
    if claim.claim_id:
        topaz_key = claim.claim_id.strip()
        candidates = billing_by_topaz_id.get(topaz_key, [])
        if candidates and claim_name:
            best_br = None
            best_score = 0
            for c in candidates:
                norm = billing_norm_names.get(c.id, "")
                name_score = fuzz.token_sort_ratio(claim_name, norm) if norm else 0
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
            norm = billing_norm_names.get(br.id, "")
            score = fuzz.token_sort_ratio(claim_name, norm)
            if score < 95:
                continue
            if claim_modality and br.modality and claim_modality.upper() == br.modality.upper():
                return br, 0.95, "pass_2_strong"
            if score >= 98:
                return br, 0.95, "pass_2_strong"

    # Pass 3: Medium fuzzy (name>=90 + date)
    if claim_name and claim_date:
        for br in billing_by_date.get(claim_date, []):
            score = fuzz.token_sort_ratio(claim_name, billing_norm_names.get(br.id, ""))
            if score >= 90:
                return br, 0.85, "pass_3_medium"

    # Pass 4: Weak fuzzy (name>=85 + date ±3 days)
    if claim_name and claim_date:
        for offset in range(-3, 4):
            check_date = claim_date + timedelta(days=offset)
            for br in billing_by_date.get(check_date, []):
                score = fuzz.token_sort_ratio(claim_name, billing_norm_names.get(br.id, ""))
                if score >= 85:
                    return br, 0.70, "pass_4_weak"

    # Pass 5: Amount-anchored (carrier + date + amount)
    if claim_date and claim_paid and claim_paid > 0 and era_payment and era_payment.payer_name:
        payer_upper = era_payment.payer_name.upper()
        for br in billing_by_date.get(claim_date, []):
            if not br.total_payment or abs(float(br.total_payment) - claim_paid) > 0.01:
                continue
            if br.insurance_carrier:
                carrier_score = fuzz.token_sort_ratio(br.insurance_carrier.upper(), payer_upper)
                if carrier_score >= 60:
                    return br, 0.75, "pass_5_amount"

    # Pass 6: Name + amount (NO date required) — for claims missing service_date
    if claim_name and claim_paid and claim_paid > 0:
        candidates = billing_by_name.get(claim_name, [])
        # Try exact name match + amount
        for br in candidates:
            if br.total_payment and abs(float(br.total_payment) - claim_paid) < 0.01:
                return br, 0.65, "pass_6_name_amount"
        # Also try fuzzy name (>=90) across all billing records by checking
        # name keys that are similar
        if not candidates:
            for name_key, brs in billing_by_name.items():
                score = fuzz.token_sort_ratio(claim_name, name_key)
                if score >= 90:
                    for br in brs:
                        if br.total_payment and claim_paid and abs(float(br.total_payment) - claim_paid) < 0.01:
                            return br, 0.60, "pass_6_name_amount"

    # Pass 7: Name only (NO date required) — strong name match, single billing record
    if claim_name:
        candidates = billing_by_name.get(claim_name, [])
        if len(candidates) == 1:
            return candidates[0], 0.55, "pass_7_name_only"

    return None, 0, None


async def run_auto_match(session: AsyncSession) -> dict:
    """
    Run all 8 matching passes on unmatched ERA claim lines.

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
    billing_by_date = defaultdict(list)
    billing_by_name = defaultdict(list)  # name-only index for dateless passes
    billing_norm_names = {}
    for br in billing_records:
        norm = _normalize_name(br.patient_name)
        billing_norm_names[br.id] = norm
        billing_by_name_date[(norm, br.service_date)].append(br)
        billing_by_date[br.service_date].append(br)
        billing_by_name[norm].append(br)
        if br.topaz_id:
            billing_by_topaz_id[br.topaz_id.strip()].append(br)

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
        f"{len(billing_by_topaz_id)} unique topaz_ids in billing. "
        f"Claims missing: name={claims_no_name}, date={claims_no_date}, both={claims_no_both}"
    )

    stats = {
        "pass_0_topaz_id": 0,
        "pass_1_exact": 0,
        "pass_2_strong": 0,
        "pass_3_medium": 0,
        "pass_4_weak": 0,
        "pass_5_amount": 0,
        "pass_6_name_amount": 0,
        "pass_7_name_only": 0,
        "unmatched": 0,
        "total": len(unmatched_claims),
    }

    pending_commits = 0

    for i, claim in enumerate(unmatched_claims):
        claim_name = _normalize_name(claim.patient_name_835)
        claim_date = claim.service_date_835
        claim_paid = round(float(claim.paid_amount), 2) if claim.paid_amount else None
        claim_cpt = claim.cpt_code
        claim_modality = CPT_TO_MODALITY.get(claim_cpt) if claim_cpt else None
        era_payment = payments_by_id.get(claim.era_payment_id)

        matched_br, confidence, pass_name = _match_single_claim(
            claim, claim_name, claim_date, claim_paid, claim_cpt, claim_modality,
            era_payment,
            billing_by_name_date, billing_by_date, billing_by_topaz_id,
            billing_norm_names, billing_by_name,
        )

        if matched_br:
            stats[pass_name] += 1

            # Apply match — many-to-one: don't remove billing record from indexes
            claim.matched_billing_id = matched_br.id
            claim.match_confidence = confidence

            # Store first claim_id as back-reference (don't overwrite if already set)
            if not matched_br.era_claim_id:
                matched_br.era_claim_id = claim.claim_id

            # NOTE: We do NOT auto-assign topaz_id from ERA claim matches.
            # topaz_id should only come from user-approved crosswalk imports.
            # The era_claim_id (set above) tracks the ERA linkage separately.

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
        f"P0:{stats['pass_0_topaz_id']} P1:{stats['pass_1_exact']} P2:{stats['pass_2_strong']} "
        f"P3:{stats['pass_3_medium']} P4:{stats['pass_4_weak']} P5:{stats['pass_5_amount']} "
        f"P6:{stats['pass_6_name_amount']} P7:{stats['pass_7_name_only']}"
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
