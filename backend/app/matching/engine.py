"""
Multi-pass payment matching engine.

Pass 1 — Exact:    claim_number + check_number + DOS
Pass 2 — Near:     patient fuzzy (≥90%) + DOS exact + CPT codes
Pass 3 — Partial:  patient fuzzy (≥85%) + DOS within 3 days
Pass 4 — Manual:   queue for staff review

All thresholds are configurable via Settings.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import List, Optional, Tuple

from rapidfuzz import fuzz
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings


@dataclass
class MatchResult:
    claim_id: Optional[int] = None
    confidence: float = 0.0
    pass_number: Optional[int] = None  # 1-4
    pass_name: str = "no_match"
    reason: str = ""
    needs_review: bool = False


@dataclass
class EOBLineData:
    """Parsed line item from an EOB document."""
    patient_name: str
    date_of_service: date
    cpt_codes: List[str] = field(default_factory=list)
    check_number: Optional[str] = None
    claim_number_raw: Optional[str] = None
    paid_amount: Optional[float] = None
    billed_amount: Optional[float] = None


async def match_eob_line(
    line: EOBLineData,
    db: AsyncSession,
) -> MatchResult:
    """
    Run a EOB line through the 4-pass matching engine.
    Returns the best MatchResult found.
    """
    # ── Pass 1: Exact match on claim_number + check_number + DOS ─────────────
    if line.claim_number_raw:
        result = await _pass1_exact(line, db)
        if result.claim_id:
            return result

    # ── Pass 2: Fuzzy patient name (≥90%) + exact DOS + CPT codes ────────────
    result = await _pass2_near(line, db)
    if result.claim_id:
        return result

    # ── Pass 3: Fuzzy patient name (≥85%) + DOS within 3 days ────────────────
    result = await _pass3_partial(line, db)
    if result.claim_id:
        return result

    # ── Pass 4: Manual queue ───────────────────────────────────────────────────
    return MatchResult(
        pass_number=4,
        pass_name="manual_queue",
        needs_review=True,
        reason="No automatic match found — requires staff review",
    )


async def _pass1_exact(line: EOBLineData, db: AsyncSession) -> MatchResult:
    """Exact match: claim_number + (optional check_number) + DOS."""
    from app.models.claim import Claim

    q = select(Claim).where(Claim.claim_number == line.claim_number_raw)
    if line.date_of_service:
        q = q.where(Claim.date_of_service == line.date_of_service)

    result = await db.execute(q)
    claim = result.scalar_one_or_none()

    if claim:
        return MatchResult(
            claim_id=claim.id,
            confidence=100.0,
            pass_number=1,
            pass_name="exact_match",
            reason=f"Exact match on claim_number={line.claim_number_raw}",
        )
    return MatchResult()


async def _pass2_near(line: EOBLineData, db: AsyncSession) -> MatchResult:
    """Near match: fuzzy patient name ≥90% + exact DOS + CPT overlap."""
    from app.models.claim import Claim
    from app.models.scan import Scan
    from app.models.appointment import Appointment
    from app.models.patient import Patient

    if not line.date_of_service:
        return MatchResult()

    # Get claims matching the exact DOS
    result = await db.execute(
        select(Claim, Patient.first_name, Patient.last_name, Scan.cpt_codes)
        .join(Scan, Claim.scan_id == Scan.id)
        .join(Appointment, Scan.appointment_id == Appointment.id)
        .join(Patient, Appointment.patient_id == Patient.id)
        .where(Claim.date_of_service == line.date_of_service)
    )
    rows = result.all()

    best_score = 0.0
    best_claim_id = None
    best_reason = ""

    for claim, first_name, last_name, cpt_codes in rows:
        full_name = f"{first_name} {last_name}"
        name_score = fuzz.token_sort_ratio(line.patient_name.lower(), full_name.lower())
        if name_score < 90:
            continue

        # Check CPT overlap
        if line.cpt_codes and cpt_codes:
            cpt_overlap = len(set(line.cpt_codes) & set(cpt_codes)) / max(len(line.cpt_codes), len(cpt_codes))
        else:
            cpt_overlap = 0.5  # no CPT data, give half credit

        combined_score = (name_score * 0.6) + (cpt_overlap * 100 * 0.4)

        if combined_score > best_score:
            best_score = combined_score
            best_claim_id = claim.id
            best_reason = (
                f"Near match: name_score={name_score:.0f}% "
                f"cpt_overlap={cpt_overlap:.0%} combined={combined_score:.0f}%"
            )

    if best_claim_id:
        return MatchResult(
            claim_id=best_claim_id,
            confidence=round(best_score, 1),
            pass_number=2,
            pass_name="near_match",
            reason=best_reason,
            needs_review=best_score < settings.EOB_AUTO_POST_THRESHOLD,
        )
    return MatchResult()


async def _pass3_partial(line: EOBLineData, db: AsyncSession) -> MatchResult:
    """Partial match: fuzzy patient name ≥85% + DOS within 3 days."""
    from app.models.claim import Claim
    from app.models.scan import Scan
    from app.models.appointment import Appointment
    from app.models.patient import Patient

    if not line.date_of_service:
        return MatchResult()

    date_min = line.date_of_service - timedelta(days=3)
    date_max = line.date_of_service + timedelta(days=3)

    result = await db.execute(
        select(Claim, Patient.first_name, Patient.last_name)
        .join(Scan, Claim.scan_id == Scan.id)
        .join(Appointment, Scan.appointment_id == Appointment.id)
        .join(Patient, Appointment.patient_id == Patient.id)
        .where(and_(Claim.date_of_service >= date_min, Claim.date_of_service <= date_max))
    )
    rows = result.all()

    best_score = 0.0
    best_claim_id = None
    best_reason = ""

    for claim, first_name, last_name in rows:
        full_name = f"{first_name} {last_name}"
        name_score = fuzz.token_sort_ratio(line.patient_name.lower(), full_name.lower())
        if name_score < 85:
            continue
        # Slight penalty for each day apart
        days_apart = abs((line.date_of_service - claim.date_of_service).days) if claim.date_of_service else 0
        date_penalty = days_apart * 2  # 2 pts per day
        combined = max(0, name_score - date_penalty)

        if combined > best_score:
            best_score = combined
            best_claim_id = claim.id
            best_reason = (
                f"Partial match: name_score={name_score:.0f}% "
                f"days_apart={days_apart} combined={combined:.0f}%"
            )

    if best_claim_id:
        return MatchResult(
            claim_id=best_claim_id,
            confidence=round(best_score, 1),
            pass_number=3,
            pass_name="partial_match",
            reason=best_reason,
            needs_review=True,  # partial always needs review
        )
    return MatchResult()


async def run_reconciliation(
    claim_id: int,
    actual_payment: float,
    db: AsyncSession,
) -> None:
    """
    After payment is matched, compute and persist reconciliation record.
    Flags if |variance| > $10 or > 5%.
    """
    from app.models.claim import Claim
    from app.models.reconciliation import Reconciliation
    from app.models.learning import BusinessRule

    claim_result = await db.execute(select(Claim).where(Claim.id == claim_id))
    claim = claim_result.scalar_one_or_none()
    if not claim:
        return

    # Calculate expected from business rules or allowed_amount
    expected = await _calculate_expected_payment(claim, db)

    variance = round((expected or 0) - actual_payment, 2)
    variance_pct = round(variance / expected * 100, 2) if expected else None
    flagged = abs(variance) > 10 or (variance_pct is not None and abs(variance_pct) > 5)

    # Upsert reconciliation
    existing = await db.execute(
        select(Reconciliation).where(Reconciliation.claim_id == claim_id)
    )
    recon = existing.scalar_one_or_none()

    if recon:
        recon.actual_payment = actual_payment
        recon.expected_payment = expected
        recon.variance = variance
        recon.variance_pct = variance_pct
        recon.flagged_for_review = flagged
        if not flagged:
            recon.reconciliation_status = "matched"
        else:
            recon.reconciliation_status = "partial" if actual_payment > 0 else "unmatched"
    else:
        recon = Reconciliation(
            claim_id=claim_id,
            expected_payment=expected,
            actual_payment=actual_payment,
            variance=variance,
            variance_pct=variance_pct,
            flagged_for_review=flagged,
            reconciliation_status="matched" if not flagged else "partial",
        )
        db.add(recon)


async def _calculate_expected_payment(claim, db: AsyncSession) -> Optional[float]:
    """
    Calculate expected payment using business rules or allowed_amount fallback.
    """
    from app.models.learning import BusinessRule
    from app.models.scan import Scan
    from app.models.insurance import Insurance

    if claim.allowed_amount:
        return float(claim.allowed_amount)

    # Try to find a matching business rule
    scan_result = await db.execute(select(Scan).where(Scan.id == claim.scan_id))
    scan = scan_result.scalar_one_or_none()
    cpt = (scan.cpt_codes or [""])[0] if scan else None

    if claim.insurance_id:
        ins_result = await db.execute(select(Insurance).where(Insurance.id == claim.insurance_id))
        ins = ins_result.scalar_one_or_none()
        payer_name = ins.payer_name if ins else None
    else:
        payer_name = None

    # Look for the most specific matching rule
    rule_result = await db.execute(
        select(BusinessRule)
        .where(
            and_(
                BusinessRule.is_active.is_(True),
                BusinessRule.cpt_code == cpt,
                BusinessRule.payer_name == payer_name,
            )
        )
        .limit(1)
    )
    rule = rule_result.scalar_one_or_none()

    if rule and claim.billed_amount:
        params = rule.rule_params or {}
        if rule.rule_type == "pct_of_billed":
            return round(float(claim.billed_amount) * params.get("percentage", 1.0), 2)
        elif rule.rule_type == "fixed_amount":
            return params.get("amount")

    return float(claim.billed_amount) if claim.billed_amount else None
