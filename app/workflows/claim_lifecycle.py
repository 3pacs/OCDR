"""
State machine for claim status tracking.

Enforces valid status transitions and records a full audit trail in the
claim_status_history table. Provides lifecycle summary queries.
"""

from datetime import datetime, timezone
from sqlalchemy import func
from app.models import db, BillingRecord, ClaimStatusHistory


# ── Valid state transitions ────────────────────────────────────────
# Keys are current states; values are lists of allowed next states.
VALID_TRANSITIONS = {
    "SUBMITTED": ["PENDING", "DENIED"],
    "PENDING": ["PAID", "DENIED", "PARTIAL"],
    "DENIED": ["APPEALED", "WRITTEN_OFF"],
    "APPEALED": ["PAID", "PARTIAL", "WRITTEN_OFF"],
    "PAID": [],
    "PARTIAL": ["PAID"],
    "WRITTEN_OFF": [],
}

# All recognized lifecycle states
ALL_STATES = list(VALID_TRANSITIONS.keys())


def _utcnow():
    """Return timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def transition_claim(
    billing_id: int,
    new_status: str,
    changed_by: str = "SYSTEM",
    notes: str = None,
) -> dict:
    """Transition a claim to a new status, enforcing valid transitions.

    Validates that:
    - The billing record exists.
    - The new_status is a recognized lifecycle state.
    - The transition from the current status to new_status is allowed.

    Records the transition in claim_status_history and updates the
    billing record's denial_status field.

    Args:
        billing_id: The BillingRecord.id to transition.
        new_status: The target lifecycle state.
        changed_by: Identifier for who/what initiated the transition.
        notes: Optional free-text notes about the transition.

    Returns:
        {
            "success": bool,
            "error": str or None,
            "billing_id": int,
            "old_status": str or None,
            "new_status": str,
        }
    """
    new_status = new_status.upper().strip()

    # Validate new_status is recognized
    if new_status not in VALID_TRANSITIONS:
        return {
            "success": False,
            "error": f"Unrecognized status: '{new_status}'. "
                     f"Valid states: {', '.join(ALL_STATES)}",
            "billing_id": billing_id,
            "old_status": None,
            "new_status": new_status,
        }

    # Fetch the billing record
    record = db.session.get(BillingRecord, billing_id)
    if record is None:
        return {
            "success": False,
            "error": f"Billing record {billing_id} not found.",
            "billing_id": billing_id,
            "old_status": None,
            "new_status": new_status,
        }

    # Determine current status
    old_status = (record.denial_status or "").upper().strip()

    # If the record has no status yet, treat it as an initial transition
    # and allow setting to SUBMITTED (or any valid first state)
    if not old_status:
        # Allow initial state assignment
        pass
    elif old_status not in VALID_TRANSITIONS:
        # Current status is not a recognized lifecycle state;
        # allow transition but log a warning in notes
        notes_prefix = f"[WARNING] Previous status '{old_status}' not in lifecycle. "
        notes = notes_prefix + (notes or "")
    else:
        # Enforce transition rules
        allowed = VALID_TRANSITIONS[old_status]
        if new_status not in allowed:
            allowed_str = ", ".join(allowed) if allowed else "(terminal state)"
            return {
                "success": False,
                "error": (
                    f"Invalid transition: {old_status} -> {new_status}. "
                    f"Allowed transitions from {old_status}: {allowed_str}"
                ),
                "billing_id": billing_id,
                "old_status": old_status,
                "new_status": new_status,
            }

    # Record the transition in history
    history_entry = ClaimStatusHistory(
        billing_record_id=billing_id,
        old_status=old_status or None,
        new_status=new_status,
        changed_by=changed_by,
        notes=notes,
    )
    db.session.add(history_entry)

    # Update the billing record
    record.denial_status = new_status
    db.session.commit()

    return {
        "success": True,
        "error": None,
        "billing_id": billing_id,
        "old_status": old_status or None,
        "new_status": new_status,
    }


def get_claim_history(billing_id: int) -> list:
    """Get the full status history for a claim.

    Args:
        billing_id: The BillingRecord.id to look up.

    Returns:
        List of dicts ordered by created_at ascending:
        [
            {
                "id": int,
                "old_status": str or None,
                "new_status": str,
                "changed_by": str,
                "notes": str or None,
                "created_at": str (ISO format),
            },
            ...
        ]
    """
    entries = (
        ClaimStatusHistory.query
        .filter_by(billing_record_id=billing_id)
        .order_by(ClaimStatusHistory.created_at.asc())
        .all()
    )
    return [
        {
            "id": e.id,
            "old_status": e.old_status,
            "new_status": e.new_status,
            "changed_by": e.changed_by,
            "notes": e.notes,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        }
        for e in entries
    ]


def get_lifecycle_summary() -> dict:
    """Get counts of claims in each lifecycle state.

    Uses a single aggregate query grouped by denial_status.

    Returns:
        {
            "states": {
                "SUBMITTED": int,
                "PENDING": int,
                "PAID": int,
                "DENIED": int,
                "APPEALED": int,
                "PARTIAL": int,
                "WRITTEN_OFF": int,
            },
            "untracked": int,  # records with null/unrecognized status
            "total": int,
        }
    """
    rows = (
        db.session.query(
            BillingRecord.denial_status,
            func.count(BillingRecord.id),
        )
        .group_by(BillingRecord.denial_status)
        .all()
    )

    states = {s: 0 for s in ALL_STATES}
    untracked = 0
    total = 0

    for status_val, count in rows:
        total += count
        normalized = (status_val or "").upper().strip()
        if normalized in states:
            states[normalized] += count
        else:
            untracked += count

    return {
        "states": states,
        "untracked": untracked,
        "total": total,
    }
