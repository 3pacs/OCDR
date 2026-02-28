"""Normalization Learning (SM-09).

Detects unmapped modality/carrier values and suggests mappings.
Stores user-approved normalizations for future use.
"""

from sqlalchemy import func

from app.models import db, NormalizationLearned, BillingRecord
from app.import_engine.validation import MODALITY_MAP, CARRIER_NORMALIZE


def get_pending_normalizations():
    """Get unmapped values that need user approval."""
    return NormalizationLearned.query.filter_by(approved=False).all()


def get_approved_normalizations(category=None):
    """Get approved normalizations, optionally filtered by category."""
    query = NormalizationLearned.query.filter_by(approved=True)
    if category:
        query = query.filter_by(category=category)
    return {n.raw_value.upper(): n.normalized_value for n in query.all()}


def suggest_normalization(raw_value, category):
    """Suggest a normalization for an unmapped value.

    Uses string similarity against known values to find best match.
    """
    if not raw_value:
        return None

    upper = raw_value.strip().upper()
    known_map = MODALITY_MAP if category == "MODALITY" else CARRIER_NORMALIZE

    # Already mapped?
    if upper in known_map:
        return None

    # Already in learned?
    existing = NormalizationLearned.query.filter_by(
        category=category, raw_value=upper
    ).first()
    if existing:
        existing.use_count += 1
        db.session.commit()
        return existing.normalized_value if existing.approved else None

    # Find closest match using simple substring matching
    best_match = None
    for known_key, known_val in known_map.items():
        if known_key in upper or upper in known_key:
            best_match = known_val
            break

    # Store as pending suggestion
    db.session.add(NormalizationLearned(
        category=category,
        raw_value=upper,
        normalized_value=best_match or upper,
        approved=False,
        use_count=1,
    ))
    db.session.commit()
    return None


def approve_normalization(normalization_id, normalized_value=None):
    """Approve a normalization suggestion, optionally overriding the value."""
    norm = db.session.get(NormalizationLearned, normalization_id)
    if not norm:
        return None
    if normalized_value:
        norm.normalized_value = normalized_value
    norm.approved = True
    db.session.commit()
    return norm


def reject_normalization(normalization_id):
    """Reject and remove a normalization suggestion."""
    norm = db.session.get(NormalizationLearned, normalization_id)
    if norm:
        db.session.delete(norm)
        db.session.commit()
    return True


def enhanced_normalize_modality(val):
    """Normalize modality using both hardcoded and learned maps."""
    from app.import_engine.validation import normalize_modality
    if not val:
        return "HMRI"

    upper = str(val).strip().upper()
    # Try hardcoded first
    result = MODALITY_MAP.get(upper)
    if result:
        return result

    # Try learned
    learned = get_approved_normalizations("MODALITY")
    if upper in learned:
        return learned[upper]

    # Suggest for future
    suggest_normalization(upper, "MODALITY")
    return upper


def enhanced_normalize_carrier(val):
    """Normalize carrier using both hardcoded and learned maps."""
    if not val:
        return "UNKNOWN"

    upper = str(val).strip().upper()
    result = CARRIER_NORMALIZE.get(upper)
    if result:
        return result

    learned = get_approved_normalizations("CARRIER")
    if upper in learned:
        return learned[upper]

    suggest_normalization(upper, "CARRIER")
    return upper
