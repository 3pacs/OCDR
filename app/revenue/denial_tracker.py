"""Denial Tracking & Appeal Queue (F-04).

Manages denial lifecycle: DENIED → APPEALED → RESOLVED / WRITTEN_OFF.
Prioritizes by recoverability score = billed_amount * (1 - days_old/365).
"""

from datetime import date, timedelta

from app.models import db, BillingRecord, EraClaimLine


DENIAL_STATUSES = ("DENIED", "APPEALED", "RESOLVED", "WRITTEN_OFF")


def get_denial_queue(carrier=None, modality=None, status_filter=None,
                     sort_by="recoverability", page=1, per_page=50):
    """Get prioritized denial queue.

    Returns billing records with $0 payment or explicit denial status,
    sorted by recoverability score (highest-value, most-recent first).
    """
    today = date.today()
    query = BillingRecord.query.filter(BillingRecord.total_payment == 0)

    if carrier:
        query = query.filter(BillingRecord.insurance_carrier == carrier)
    if modality:
        query = query.filter(BillingRecord.modality == modality)
    if status_filter and status_filter in DENIAL_STATUSES:
        query = query.filter(BillingRecord.denial_status == status_filter)

    records = query.all()

    items = []
    for r in records:
        days_old = (today - r.service_date).days if r.service_date else 0
        recoverability = _recoverability_score(r, days_old)

        # Find matching ERA claim line for CAS codes
        era_info = {}
        if r.era_claim_id:
            era_claim = EraClaimLine.query.filter_by(claim_id=r.era_claim_id).first()
            if era_claim:
                era_info = {
                    "cas_group_code": era_claim.cas_group_code,
                    "cas_reason_code": era_claim.cas_reason_code,
                    "cas_adjustment_amount": era_claim.cas_adjustment_amount,
                    "billed_amount_835": era_claim.billed_amount,
                }

        items.append({
            **r.to_dict(),
            "days_old": days_old,
            "recoverability_score": round(recoverability, 2),
            "denial_status": r.denial_status or "DENIED",
            **era_info,
        })

    # Sort
    if sort_by == "recoverability":
        items.sort(key=lambda x: x["recoverability_score"], reverse=True)
    elif sort_by == "amount":
        items.sort(key=lambda x: x.get("billed_amount_835", 0), reverse=True)
    elif sort_by == "age":
        items.sort(key=lambda x: x["days_old"])

    total = len(items)
    start = (page - 1) * per_page
    end = start + per_page

    return {
        "items": items[start:end],
        "total": total,
        "page": page,
        "pages": (total + per_page - 1) // per_page,
        "summary": {
            "total_denied": total,
            "total_recoverable": round(sum(i["recoverability_score"] for i in items), 2),
            "by_status": _count_by_status(items),
        }
    }


def appeal_denial(billing_id, notes=None):
    """Mark a denied claim as appealed."""
    record = BillingRecord.query.get(billing_id)
    if not record:
        return {"error": "Record not found"}
    record.denial_status = "APPEALED"
    db.session.commit()
    return {"status": "appealed", "id": billing_id}


def resolve_denial(billing_id, resolution="RESOLVED", payment_amount=None):
    """Resolve a denied claim (paid after appeal or written off)."""
    record = BillingRecord.query.get(billing_id)
    if not record:
        return {"error": "Record not found"}

    record.denial_status = resolution
    if payment_amount is not None:
        record.total_payment = payment_amount
        record.primary_payment = payment_amount
    db.session.commit()
    return {"status": resolution.lower(), "id": billing_id}


def bulk_appeal(billing_ids):
    """Mark multiple claims as appealed in bulk."""
    count = 0
    for bid in billing_ids:
        record = BillingRecord.query.get(bid)
        if record and record.total_payment == 0:
            record.denial_status = "APPEALED"
            count += 1
    db.session.commit()
    return {"appealed": count}


def _recoverability_score(record, days_old):
    """Compute recoverability: higher for newer, higher-value claims."""
    from app.models import FeeSchedule
    # Estimate expected value from fee schedule
    fs = FeeSchedule.query.filter_by(payer_code=record.insurance_carrier, modality=record.modality).first()
    if not fs:
        fs = FeeSchedule.query.filter_by(payer_code="DEFAULT", modality=record.modality).first()
    expected = fs.expected_rate if fs else 500.0
    return expected * max(0, 1 - (days_old / 365))


def _count_by_status(items):
    counts = {}
    for i in items:
        s = i.get("denial_status", "DENIED")
        counts[s] = counts.get(s, 0) + 1
    return counts
