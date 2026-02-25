"""Weight Optimizer — Learns optimal match weights and thresholds (SM-01b, SM-02).

Uses logistic regression on match outcomes to find weights that maximize
correct accept/reject predictions per carrier/modality combination.

Threshold optimizer finds per-carrier auto-accept/review thresholds
based on precision/recall metrics from historical outcomes.
"""

import math
from datetime import datetime

from sqlalchemy import func

from app.models import db, MatchOutcome, LearnedWeights


# ── Constants ────────────────────────────────────────────────────

MIN_SAMPLES_FOR_LEARNING = 50
MIN_WEIGHT = 0.05
WEIGHT_SUM = 1.0
LEARNING_RATE = 0.01
MAX_ITERATIONS = 100
MIN_PRECISION_AUTO_ACCEPT = 0.95
MIN_PRECISION_REVIEW = 0.80


# ── SM-01b: Weight Optimization ─────────────────────────────────

def optimize_weights(carrier=None, modality=None):
    """Compute optimal weights for a carrier/modality from match outcomes.

    Uses gradient descent on logistic loss to find weights that best
    predict confirmed vs rejected outcomes.

    Returns dict with weights or None if insufficient data.
    """
    query = MatchOutcome.query.filter(
        MatchOutcome.name_score.isnot(None),
        MatchOutcome.date_score.isnot(None),
        MatchOutcome.modality_score.isnot(None),
        MatchOutcome.action.in_(["CONFIRMED", "REJECTED"]),
    )
    if carrier:
        query = query.filter(MatchOutcome.carrier == carrier)
    if modality:
        query = query.filter(MatchOutcome.modality == modality)

    outcomes = query.all()
    if len(outcomes) < MIN_SAMPLES_FOR_LEARNING:
        return None

    # Prepare training data
    X = []  # (name_score, date_score, modality_score)
    y = []  # 1 = confirmed, 0 = rejected
    for o in outcomes:
        X.append((o.name_score, o.date_score, o.modality_score))
        y.append(1.0 if o.action == "CONFIRMED" else 0.0)

    # Gradient descent on logistic loss with constrained weights
    w = [0.50, 0.30, 0.20]  # Start from defaults
    best_w = list(w)
    best_loss = _compute_loss(X, y, w)

    for _ in range(MAX_ITERATIONS):
        grads = _compute_gradients(X, y, w)
        for i in range(3):
            w[i] -= LEARNING_RATE * grads[i]
        # Enforce constraints: all > MIN_WEIGHT, sum = 1.0
        w = _project_weights(w)
        loss = _compute_loss(X, y, w)
        if loss < best_loss:
            best_loss = loss
            best_w = list(w)

    accuracy = _compute_accuracy(X, y, best_w)

    return {
        "name_weight": round(best_w[0], 4),
        "date_weight": round(best_w[1], 4),
        "modality_weight": round(best_w[2], 4),
        "sample_size": len(outcomes),
        "accuracy": round(accuracy, 4),
    }


def _sigmoid(z):
    """Numerically stable sigmoid."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)


def _compute_loss(X, y, w):
    """Binary cross-entropy loss."""
    loss = 0.0
    for (ns, ds, ms), label in zip(X, y):
        z = w[0] * ns + w[1] * ds + w[2] * ms
        p = _sigmoid(z * 5.0)  # Scale to sharpen sigmoid
        p = max(1e-7, min(1 - 1e-7, p))
        loss += -(label * math.log(p) + (1 - label) * math.log(1 - p))
    return loss / len(X)


def _compute_gradients(X, y, w):
    """Gradient of binary cross-entropy."""
    grads = [0.0, 0.0, 0.0]
    for (ns, ds, ms), label in zip(X, y):
        scores = [ns, ds, ms]
        z = sum(w[i] * scores[i] for i in range(3))
        p = _sigmoid(z * 5.0)
        error = p - label
        for i in range(3):
            grads[i] += error * scores[i] * 5.0
    return [g / len(X) for g in grads]


def _compute_accuracy(X, y, w):
    """Compute classification accuracy at threshold 0.5."""
    correct = 0
    for (ns, ds, ms), label in zip(X, y):
        z = w[0] * ns + w[1] * ds + w[2] * ms
        pred = 1.0 if z >= 0.5 else 0.0
        if pred == label:
            correct += 1
    return correct / len(X) if X else 0.0


def _project_weights(w):
    """Project weights to satisfy: all >= MIN_WEIGHT, sum = 1.0."""
    w = [max(MIN_WEIGHT, x) for x in w]
    total = sum(w)
    return [x / total for x in w]


# ── SM-02: Threshold Optimization ───────────────────────────────

def optimize_thresholds(carrier=None, modality=None):
    """Compute optimal auto-accept and review thresholds from outcomes.

    Finds the lowest threshold where precision >= target.
    Returns dict with thresholds or None if insufficient data.
    """
    query = MatchOutcome.query.filter(
        MatchOutcome.original_score.isnot(None),
        MatchOutcome.action.in_(["CONFIRMED", "REJECTED"]),
    )
    if carrier:
        query = query.filter(MatchOutcome.carrier == carrier)
    if modality:
        query = query.filter(MatchOutcome.modality == modality)

    outcomes = query.all()
    if len(outcomes) < MIN_SAMPLES_FOR_LEARNING:
        return None

    scores_labels = [(o.original_score, o.action == "CONFIRMED") for o in outcomes]
    scores_labels.sort(key=lambda x: x[0])

    # Find optimal thresholds
    auto_accept = 0.95  # default
    review = 0.80  # default

    for threshold in [x / 100.0 for x in range(70, 100)]:
        precision = _precision_at_threshold(scores_labels, threshold)
        if precision >= MIN_PRECISION_AUTO_ACCEPT and threshold < auto_accept:
            auto_accept = threshold
        if precision >= MIN_PRECISION_REVIEW and threshold < review:
            review = threshold

    # Ensure auto_accept > review + 0.05
    if auto_accept < review + 0.05:
        auto_accept = min(0.99, review + 0.05)

    return {
        "auto_accept_threshold": round(auto_accept, 2),
        "review_threshold": round(review, 2),
        "sample_size": len(outcomes),
    }


def _precision_at_threshold(scores_labels, threshold):
    """Compute precision at a given threshold."""
    tp = sum(1 for score, label in scores_labels if score >= threshold and label)
    fp = sum(1 for score, label in scores_labels if score >= threshold and not label)
    return tp / (tp + fp) if (tp + fp) > 0 else 1.0


# ── Store/Retrieve Learned Weights ──────────────────────────────

def update_learned_weights(carrier=None, modality=None):
    """Run weight + threshold optimization and store results.

    Called after new outcomes are recorded.
    Returns the stored LearnedWeights or None if not enough data.
    """
    weights = optimize_weights(carrier=carrier, modality=modality)
    thresholds = optimize_thresholds(carrier=carrier, modality=modality)

    if not weights and not thresholds:
        return None

    # Find or create record
    existing = LearnedWeights.query.filter_by(
        carrier=carrier, modality=modality
    ).first()

    if not existing:
        existing = LearnedWeights(carrier=carrier, modality=modality)
        db.session.add(existing)

    if weights:
        existing.name_weight = weights["name_weight"]
        existing.date_weight = weights["date_weight"]
        existing.modality_weight = weights["modality_weight"]
        existing.sample_size = weights["sample_size"]
        existing.accuracy = weights["accuracy"]

    if thresholds:
        existing.auto_accept_threshold = thresholds["auto_accept_threshold"]
        existing.review_threshold = thresholds["review_threshold"]
        if not weights:
            existing.sample_size = thresholds["sample_size"]

    existing.updated_at = datetime.utcnow()
    db.session.commit()
    return existing


def get_learned_weights(carrier=None, modality=None):
    """Get learned weights, falling back through the hierarchy:

    carrier+modality -> carrier-only -> modality-only -> global -> defaults
    """
    # Try exact match first
    for c, m in [(carrier, modality), (carrier, None), (None, modality), (None, None)]:
        lw = LearnedWeights.query.filter_by(carrier=c, modality=m).first()
        if lw and lw.sample_size >= MIN_SAMPLES_FOR_LEARNING:
            return {
                "name_weight": lw.name_weight,
                "date_weight": lw.date_weight,
                "modality_weight": lw.modality_weight,
                "auto_accept_threshold": lw.auto_accept_threshold,
                "review_threshold": lw.review_threshold,
                "sample_size": lw.sample_size,
                "accuracy": lw.accuracy,
                "source": f"learned:{c or 'any'}:{m or 'any'}",
            }

    # Return defaults
    return {
        "name_weight": 0.50,
        "date_weight": 0.30,
        "modality_weight": 0.20,
        "auto_accept_threshold": 0.95,
        "review_threshold": 0.80,
        "sample_size": 0,
        "accuracy": None,
        "source": "default",
    }


def get_all_learned_weights():
    """Get all stored learned weight configurations."""
    all_weights = LearnedWeights.query.order_by(
        LearnedWeights.carrier, LearnedWeights.modality
    ).all()
    return [{
        "id": w.id,
        "carrier": w.carrier,
        "modality": w.modality,
        "name_weight": w.name_weight,
        "date_weight": w.date_weight,
        "modality_weight": w.modality_weight,
        "auto_accept_threshold": w.auto_accept_threshold,
        "review_threshold": w.review_threshold,
        "sample_size": w.sample_size,
        "accuracy": w.accuracy,
        "updated_at": w.updated_at.isoformat() if w.updated_at else None,
    } for w in all_weights]


def reset_learned_weights(carrier=None, modality=None):
    """Reset learned weights to defaults. If no filter, resets all."""
    query = LearnedWeights.query
    if carrier is not None:
        query = query.filter_by(carrier=carrier)
    if modality is not None:
        query = query.filter_by(modality=modality)
    count = query.delete()
    db.session.commit()
    return count


def maybe_reoptimize(carrier=None, modality=None):
    """Check if we should re-optimize weights (every 25 new outcomes)."""
    query = MatchOutcome.query.filter(
        MatchOutcome.action.in_(["CONFIRMED", "REJECTED"]),
    )
    if carrier:
        query = query.filter(MatchOutcome.carrier == carrier)
    if modality:
        query = query.filter(MatchOutcome.modality == modality)

    count = query.count()
    if count >= MIN_SAMPLES_FOR_LEARNING and count % 25 == 0:
        update_learned_weights(carrier=carrier, modality=modality)
