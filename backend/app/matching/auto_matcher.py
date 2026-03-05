"""
5-Pass Auto-Matching Engine.

Matches ERA claim lines (from 835 files) to billing records using
progressively looser matching criteria:

  Pass 1: Exact composite (name + DOB + service_date + amount)  → 99%
  Pass 2: Strong fuzzy   (name>=95 + service_date + CPT)        → 95%
  Pass 3: Medium fuzzy   (name>=90 + service_date + modality)   → 85%
  Pass 4: Weak fuzzy     (name>=85 + service_date ±3 days)      → 70%
  Pass 5: Amount-anchor  (carrier + service_date + amount)      → 75%

After matching, updates:
  - ERAClaimLine.matched_billing_id and match_confidence
  - BillingRecord.era_claim_id, denial_status, denial_reason_code
"""

import logging
from datetime import timedelta

from rapidfuzz import fuzz
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.billing import BillingRecord
from backend.app.models.era import ERAClaimLine, ERAPayment

logger = logging.getLogger(__name__)


def _normalize_name(name: str | None) -> str:
    """Normalize patient name for matching: uppercase, strip, remove middle initials."""
    if not name:
        return ""
    parts = name.upper().strip().replace(",", ", ").split()
    parts = [p for p in parts if len(p) > 1 or p in (",",)]
    return " ".join(parts).strip().rstrip(",").lstrip(",").strip()


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
    "4": "DENIED",
    "22": "REVERSAL",
}


async def run_auto_match(session: AsyncSession) -> dict:
    """Run all 5 matching passes on unmatched ERA claim lines."""
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

    # Build indexes
    billing_by_name_date = {}
    for br in billing_records:
        norm = _normalize_name(br.patient_name)
        key = (norm, br.service_date)
        billing_by_name_date.setdefault(key, []).append(br)

    # Load ERA payments for payer name lookup
    payment_ids = {c.era_payment_id for c in unmatched_claims}
    payment_result = await session.execute(
        select(ERAPayment).where(ERAPayment.id.in_(payment_ids))
    )
    payments_by_id = {p.id: p for p in payment_result.scalars().all()}

    stats = {
        "pass_1_exact": 0,
        "pass_2_strong": 0,
        "pass_3_medium": 0,
        "pass_4_weak": 0,
        "pass_5_amount": 0,
        "unmatched": 0,
        "total": len(unmatched_claims),
    }

    matched_billing_ids = set()

    for claim in unmatched_claims:
        claim_name = _normalize_name(claim.patient_name_835)
        claim_date = claim.service_date_835
        claim_paid = round(float(claim.paid_amount), 2) if claim.paid_amount else None
        claim_cpt = claim.cpt_code
        claim_modality = CPT_TO_MODALITY.get(claim_cpt) if claim_cpt else None

        matched_br = None
        confidence = 0

        # Pass 1: Exact composite
        if claim_name and claim_date:
            key = (claim_name, claim_date)
            candidates = [c for c in billing_by_name_date.get(key, []) if c.id not in matched_billing_ids]
            for br in candidates:
                if claim_paid and br.total_payment:
                    if abs(float(br.total_payment) - claim_paid) < 0.01:
                        matched_br = br
                        confidence = 0.99
                        stats["pass_1_exact"] += 1
                        break
                if len(candidates) == 1:
                    matched_br = br
                    confidence = 0.99
                    stats["pass_1_exact"] += 1
                    break

        # Pass 2: Strong fuzzy (name>=95 + date + CPT/modality)
        if not matched_br and claim_name and claim_date:
            for br in billing_records:
                if br.id in matched_billing_ids or br.service_date != claim_date:
                    continue
                match, score = _names_match(br.patient_name, claim.patient_name_835, 95)
                if not match:
                    continue
                if claim_modality and br.modality and claim_modality.upper() == br.modality.upper():
                    matched_br = br
                    confidence = 0.95
                    stats["pass_2_strong"] += 1
                    break
                if score >= 98:
                    matched_br = br
                    confidence = 0.95
                    stats["pass_2_strong"] += 1
                    break

        # Pass 3: Medium fuzzy (name>=90 + date)
        if not matched_br and claim_name and claim_date:
            for br in billing_records:
                if br.id in matched_billing_ids or br.service_date != claim_date:
                    continue
                match, _ = _names_match(br.patient_name, claim.patient_name_835, 90)
                if match:
                    matched_br = br
                    confidence = 0.85
                    stats["pass_3_medium"] += 1
                    break

        # Pass 4: Weak fuzzy (name>=85 + date ±3 days)
        if not matched_br and claim_name and claim_date:
            date_min = claim_date - timedelta(days=3)
            date_max = claim_date + timedelta(days=3)
            for br in billing_records:
                if br.id in matched_billing_ids:
                    continue
                if not (date_min <= br.service_date <= date_max):
                    continue
                match, _ = _names_match(br.patient_name, claim.patient_name_835, 85)
                if match:
                    matched_br = br
                    confidence = 0.70
                    stats["pass_4_weak"] += 1
                    break

        # Pass 5: Amount-anchored (carrier + date + amount)
        if not matched_br and claim_date and claim_paid and claim_paid > 0:
            era_payment = payments_by_id.get(claim.era_payment_id)
            if era_payment and era_payment.payer_name:
                payer_upper = era_payment.payer_name.upper()
                for br in billing_records:
                    if br.id in matched_billing_ids or br.service_date != claim_date:
                        continue
                    if not br.total_payment or abs(float(br.total_payment) - claim_paid) > 0.01:
                        continue
                    if br.insurance_carrier:
                        carrier_score = fuzz.token_sort_ratio(br.insurance_carrier.upper(), payer_upper)
                        if carrier_score >= 60:
                            matched_br = br
                            confidence = 0.75
                            stats["pass_5_amount"] += 1
                            break

        # Apply match
        if matched_br:
            matched_billing_ids.add(matched_br.id)
            claim.matched_billing_id = matched_br.id
            claim.match_confidence = confidence
            matched_br.era_claim_id = claim.claim_id
            status = CLAIM_STATUS_MAP.get(claim.claim_status)
            if status:
                matched_br.denial_status = status
            if claim.cas_reason_code:
                matched_br.denial_reason_code = claim.cas_reason_code
            if float(matched_br.total_payment or 0) == 0 and claim.paid_amount:
                matched_br.total_payment = claim.paid_amount
        else:
            stats["unmatched"] += 1

    await session.commit()

    stats["matched_total"] = stats["total"] - stats["unmatched"]
    stats["match_rate"] = round(
        (stats["matched_total"] / stats["total"] * 100) if stats["total"] > 0 else 0, 1
    )

    logger.info(
        f"Auto-match: {stats['matched_total']}/{stats['total']} ({stats['match_rate']}%) "
        f"P1:{stats['pass_1_exact']} P2:{stats['pass_2_strong']} P3:{stats['pass_3_medium']} "
        f"P4:{stats['pass_4_weak']} P5:{stats['pass_5_amount']}"
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
        ("weak_70", 0.0, 0.74),
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
