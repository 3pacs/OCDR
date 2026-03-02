"""
Persistence layer for user approval/rejection decisions.

Stores every decision in ``data/decisions/decisions.jsonl`` so the
smart reports system can learn from past behaviour and improve
reconciliation accuracy over time.
"""

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from ocdr.config import DECISION_DIR, DECISION_HISTORY_PATH


def _ensure_dir():
    DECISION_DIR.mkdir(parents=True, exist_ok=True)


def record_decision(decision: dict) -> None:
    """Append a single decision to the history file."""
    _ensure_dir()
    decision.setdefault("timestamp", datetime.now().isoformat())
    with open(DECISION_HISTORY_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(decision, default=str, ensure_ascii=False) + "\n")


def load_all_decisions() -> list[dict]:
    """Read every decision ever recorded."""
    if not DECISION_HISTORY_PATH.exists():
        return []
    decisions = []
    with open(DECISION_HISTORY_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    decisions.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    return decisions


def load_decisions_for_payer(payer: str) -> list[dict]:
    """Filter decisions by payer name (case-insensitive)."""
    payer_upper = payer.upper()
    return [d for d in load_all_decisions()
            if (d.get("payer", "") or "").upper() == payer_upper
            or (d.get("insurance_carrier", "") or "").upper() == payer_upper]


def get_decision_stats() -> dict:
    """Compute aggregate statistics across all decisions."""
    decisions = load_all_decisions()
    if not decisions:
        return {"total": 0}

    total = len(decisions)
    approved = [d for d in decisions if d.get("user_decision") == "APPROVE"]
    rejected = [d for d in decisions if d.get("user_decision") == "REJECT"]
    skipped = [d for d in decisions if d.get("user_decision") == "SKIP"]

    auto_accepted = [d for d in approved
                     if d.get("system_status") == "AUTO_ACCEPT"]
    review_accepted = [d for d in approved
                       if d.get("system_status") == "REVIEW"]
    review_rejected = [d for d in rejected
                       if d.get("system_status") == "REVIEW"]

    def avg_score(ds):
        scores = [d.get("match_score", 0) for d in ds if d.get("match_score")]
        return sum(scores) / len(scores) if scores else 0.0

    def total_amount(ds):
        return sum(float(d.get("claim_paid", 0) or 0) for d in ds)

    return {
        "total": total,
        "approved": len(approved),
        "rejected": len(rejected),
        "skipped": len(skipped),
        "auto_accepted": len(auto_accepted),
        "review_accepted": len(review_accepted),
        "review_rejected": len(review_rejected),
        "approval_rate": len(approved) / total if total else 0.0,
        "avg_score_approved": round(avg_score(approved), 4),
        "avg_score_rejected": round(avg_score(rejected), 4),
        "total_approved_amount": round(total_amount(approved), 2),
        "total_rejected_amount": round(total_amount(rejected), 2),
        "total_skipped_amount": round(total_amount(skipped), 2),
    }


def check_duplicate_payment(patient_name: str, service_date,
                             modality: str) -> Optional[dict]:
    """Check if a payment was already applied for this patient+date+modality.

    Returns the existing decision dict if found, None otherwise.
    """
    for d in load_all_decisions():
        if (d.get("user_decision") == "APPROVE"
                and (d.get("billing_patient", "") or "").upper() == patient_name.upper()
                and str(d.get("billing_date", "")) == str(service_date)
                and (d.get("billing_modality", "") or "").upper() == modality.upper()):
            return d
    return None


def save_session_state(state: dict, path: Path) -> None:
    """Save approval session state for --resume."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, default=str, indent=2)


def load_session_state(path: Path) -> Optional[dict]:
    """Load a saved approval session."""
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
