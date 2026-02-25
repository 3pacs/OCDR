"""Match Memory — Outcome Tracking, Name Aliases, CPT Learning (SM-01a, SM-04, SM-05, SM-06).

Records every match confirm/reject with component scores.
Manages name alias pairs and CPT->modality learning.
Tracks date offset distributions for smooth scoring curves.
"""

from datetime import datetime

from app.models import (
    db, MatchOutcome, NameAlias, LearnedCptModality,
    EraClaimLine, BillingRecord,
)
from app.matching.match_engine import normalize_name


# ── SM-01a: Match Outcome Tracking ──────────────────────────────

def record_outcome(era_claim_id, billing_record_id, action,
                   original_score=None, name_score=None, date_score=None,
                   modality_score=None, carrier=None, modality=None):
    """Record a match outcome (CONFIRMED, REJECTED, REASSIGNED).

    Also triggers alias learning and CPT learning on confirmations.
    """
    outcome = MatchOutcome(
        era_claim_id=era_claim_id,
        billing_record_id=billing_record_id,
        action=action,
        original_score=original_score,
        name_score=name_score,
        date_score=date_score,
        modality_score=modality_score,
        carrier=carrier,
        modality=modality,
    )
    db.session.add(outcome)
    db.session.flush()

    if action == "CONFIRMED" and billing_record_id:
        claim = db.session.get(EraClaimLine, era_claim_id)
        billing = db.session.get(BillingRecord, billing_record_id)
        if claim and billing:
            # Learn name alias if names differ
            _learn_name_alias(claim.patient_name_835, billing.patient_name, name_score)
            # Learn CPT->modality mapping
            _learn_cpt_modality(claim.cpt_code, billing.modality)

    db.session.commit()
    return outcome.id


def get_outcomes(carrier=None, modality=None, limit=500):
    """Get match outcomes for analysis, optionally filtered."""
    query = MatchOutcome.query
    if carrier:
        query = query.filter(MatchOutcome.carrier == carrier)
    if modality:
        query = query.filter(MatchOutcome.modality == modality)
    return query.order_by(MatchOutcome.created_at.desc()).limit(limit).all()


def get_outcome_stats():
    """Get summary statistics of match outcomes."""
    from sqlalchemy import func
    total = MatchOutcome.query.count()
    by_action = db.session.query(
        MatchOutcome.action, func.count(MatchOutcome.id)
    ).group_by(MatchOutcome.action).all()
    by_carrier = db.session.query(
        MatchOutcome.carrier,
        MatchOutcome.action,
        func.count(MatchOutcome.id),
    ).group_by(MatchOutcome.carrier, MatchOutcome.action).all()

    return {
        "total_outcomes": total,
        "by_action": {a: c for a, c in by_action},
        "by_carrier": _group_carrier_stats(by_carrier),
    }


def _group_carrier_stats(rows):
    result = {}
    for carrier, action, count in rows:
        if carrier not in result:
            result[carrier] = {}
        result[carrier][action] = count
    return result


# ── SM-04: Name Alias Learning ──────────────────────────────────

def _learn_name_alias(name_835, name_billing, name_score=None):
    """Store a name alias pair if names are different enough to be interesting."""
    if not name_835 or not name_billing:
        return
    if name_score is not None and name_score >= 0.95:
        return  # Names already very similar, no alias needed

    norm_a = normalize_name(name_835)
    norm_b = normalize_name(name_billing)
    if not norm_a or not norm_b or norm_a == norm_b:
        return

    # Canonical order: alphabetical
    if norm_a > norm_b:
        norm_a, norm_b = norm_b, norm_a

    existing = NameAlias.query.filter_by(name_a=norm_a, name_b=norm_b).first()
    if existing:
        existing.match_count += 1
    else:
        db.session.add(NameAlias(name_a=norm_a, name_b=norm_b, match_count=1))


def get_active_aliases(min_count=2):
    """Get name alias pairs with enough confirmations to be trusted."""
    return NameAlias.query.filter(NameAlias.match_count >= min_count).all()


def build_alias_lookup(min_count=2):
    """Build a dict for fast alias lookups: normalized_name -> set of aliases."""
    aliases = get_active_aliases(min_count)
    lookup = {}
    for a in aliases:
        lookup.setdefault(a.name_a, set()).add(a.name_b)
        lookup.setdefault(a.name_b, set()).add(a.name_a)
    return lookup


def check_alias(name_a, name_b, alias_lookup):
    """Check if two names are known aliases. Returns True if alias pair exists."""
    if not alias_lookup:
        return False
    norm_a = normalize_name(name_a)
    norm_b = normalize_name(name_b)
    return norm_b in alias_lookup.get(norm_a, set())


# ── SM-05: CPT->Modality Learning ──────────────────────────────

def _learn_cpt_modality(cpt_str, billing_modality):
    """Learn CPT->modality mapping from a confirmed match."""
    if not cpt_str or not billing_modality:
        return
    cpt = cpt_str.split(",")[0].strip()
    if not cpt or len(cpt) < 3:
        return

    # Try both full code and 3-char prefix
    for prefix in (cpt, cpt[:3]):
        existing = db.session.get(LearnedCptModality, prefix)
        if existing:
            if existing.modality == billing_modality.upper():
                existing.match_count += 1
                existing.confidence = min(1.0, existing.match_count / 10.0)
            # Don't overwrite existing mappings with conflicting data
            continue

        # Only add full-code mapping (prefix learned from hardcoded map)
        if prefix == cpt:
            db.session.add(LearnedCptModality(
                cpt_prefix=prefix,
                modality=billing_modality.upper(),
                confidence=0.3,
                source="LEARNED",
                match_count=1,
            ))


def get_cpt_modality_map():
    """Get combined hardcoded + learned CPT->modality map."""
    from app.matching.match_engine import _cpt_to_modality as _hardcoded_lookup
    # Start with learned mappings that have enough confidence
    learned = LearnedCptModality.query.filter(
        LearnedCptModality.match_count >= 3,
        LearnedCptModality.source == "LEARNED",
    ).all()

    result = {}
    for entry in learned:
        result[entry.cpt_prefix] = {
            "modality": entry.modality,
            "source": entry.source,
            "confidence": entry.confidence,
            "match_count": entry.match_count,
        }
    return result


# ── SM-06: Date Offset Distribution ─────────────────────────────

def get_date_offset_distribution():
    """Compute date offset distribution from confirmed match outcomes.

    Returns dict of {offset_days: count} for building smooth scoring curves.
    """
    confirmed = MatchOutcome.query.filter_by(action="CONFIRMED").all()
    offsets = {}

    for outcome in confirmed:
        claim = db.session.get(EraClaimLine, outcome.era_claim_id)
        billing = db.session.get(BillingRecord, outcome.billing_record_id) if outcome.billing_record_id else None
        if claim and billing and claim.service_date_835 and billing.service_date:
            diff = abs((claim.service_date_835 - billing.service_date).days)
            offsets[diff] = offsets.get(diff, 0) + 1

    return offsets


def build_date_score_curve(min_samples=30):
    """Build a smooth date scoring curve from confirmed match date offsets.

    Returns dict {offset_days: score} or None if insufficient data.
    Uses cumulative distribution: score = P(offset <= days) mapped to 0-1.
    """
    offsets = get_date_offset_distribution()
    total = sum(offsets.values())
    if total < min_samples:
        return None

    # Build cumulative probability curve
    max_offset = min(max(offsets.keys(), default=0), 14)
    curve = {}
    for days in range(max_offset + 1):
        # Score = proportion of matches at this offset or closer
        matches_at_or_closer = sum(
            count for d, count in offsets.items() if d <= days
        )
        # Convert to score: exact match = 1.0, then decay
        if days == 0:
            curve[0] = 1.0
        else:
            proportion_beyond = 1.0 - (matches_at_or_closer / total)
            curve[days] = max(0.0, round(1.0 - proportion_beyond * 1.5, 4))

    return curve
