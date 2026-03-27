"""Confidence Calibration — Platt Scaling (SM-10).

Calibrates match confidence scores so that a score of 0.90 means
approximately 90% of matches at that score are actually correct.

Uses Platt scaling (logistic regression on raw scores) trained on
historical match outcomes.
"""

import math

from app.models import db, MatchOutcome


MIN_CALIBRATION_SAMPLES = 50


def train_calibration():
    """Train Platt scaling parameters from match outcomes.

    Fits: P(correct | score) = 1 / (1 + exp(A*score + B))
    Returns (A, B) parameters or None if insufficient data.
    """
    outcomes = MatchOutcome.query.filter(
        MatchOutcome.original_score.isnot(None),
        MatchOutcome.action.in_(["CONFIRMED", "REJECTED"]),
    ).all()

    if len(outcomes) < MIN_CALIBRATION_SAMPLES:
        return None

    scores = [o.original_score for o in outcomes]
    labels = [1.0 if o.action == "CONFIRMED" else 0.0 for o in outcomes]

    # Fit via gradient descent: P(y=1|s) = sigmoid(A*s + B)
    A, B = -5.0, 2.5  # Initial params (score increases -> more correct)
    lr = 0.01

    for _ in range(200):
        grad_A, grad_B = 0.0, 0.0
        for s, y in zip(scores, labels):
            p = _sigmoid(A * s + B)
            err = p - y
            grad_A += err * s
            grad_B += err

        A -= lr * grad_A / len(scores)
        B -= lr * grad_B / len(scores)

    return (round(A, 6), round(B, 6))


def calibrate_score(raw_score, params=None):
    """Apply Platt scaling to calibrate a raw match score.

    Args:
        raw_score: The raw composite match score (0-1)
        params: (A, B) tuple from train_calibration, or None for identity

    Returns: Calibrated probability (0-1)
    """
    if params is None or raw_score is None:
        return raw_score
    A, B = params
    return round(_sigmoid(A * raw_score + B), 4)


def get_calibration_stats(params=None):
    """Get calibration analysis: binned accuracy vs predicted probability."""
    if params is None:
        params = train_calibration()
    if params is None:
        return {"status": "insufficient_data", "bins": []}

    outcomes = MatchOutcome.query.filter(
        MatchOutcome.original_score.isnot(None),
        MatchOutcome.action.in_(["CONFIRMED", "REJECTED"]),
    ).all()

    # Bin by calibrated score
    bins = {}
    for o in outcomes:
        calibrated = calibrate_score(o.original_score, params)
        bin_key = round(calibrated * 10) / 10  # Round to nearest 0.1
        if bin_key not in bins:
            bins[bin_key] = {"total": 0, "correct": 0}
        bins[bin_key]["total"] += 1
        if o.action == "CONFIRMED":
            bins[bin_key]["correct"] += 1

    result_bins = []
    for score_bin in sorted(bins.keys()):
        data = bins[score_bin]
        result_bins.append({
            "predicted_probability": score_bin,
            "actual_accuracy": round(data["correct"] / data["total"], 4) if data["total"] > 0 else 0,
            "sample_count": data["total"],
        })

    return {
        "status": "calibrated",
        "params": {"A": params[0], "B": params[1]},
        "sample_size": len(outcomes),
        "bins": result_bins,
    }


def _sigmoid(z):
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    ez = math.exp(z)
    return ez / (1.0 + ez)
