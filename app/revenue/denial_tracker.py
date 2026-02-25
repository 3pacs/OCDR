"""Denial Tracking & Appeal Queue (F-04 + Smart Denial Intelligence).

Manages denial lifecycle: DENIED → APPEALED → RESOLVED / WRITTEN_OFF.
Prioritizes by smart recoverability using learned recovery rates (SM-03).
Performance optimized: pre-loads fee schedule and ERA claims.
"""

from datetime import date, timedelta

from app.models import db, BillingRecord, EraClaimLine, FeeSchedule


DENIAL_STATUSES = ("DENIED", "APPEALED", "RESOLVED", "WRITTEN_OFF")


def get_denial_queue(carrier=None, modality=None, status_filter=None,
                     sort_by="recoverability", page=1, per_page=50):
    """Get prioritized denial queue with smart recoverability scoring.

    Performance: pre-loads fee schedule and ERA claims to avoid N+1 queries.
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

    # Pre-load fee schedule into dict (fixes N+1)
    fee_map = {}
    for fs in FeeSchedule.query.all():
        fee_map[(fs.payer_code, fs.modality)] = fs.expected_rate
        if fs.payer_code == "DEFAULT":
            fee_map[("_default", fs.modality)] = fs.expected_rate

    # Pre-load ERA claim lines for all denial records (fixes N+1)
    era_claim_ids = [r.era_claim_id for r in records if r.era_claim_id]
    era_map = {}
    if era_claim_ids:
        era_claims = EraClaimLine.query.filter(
            EraClaimLine.claim_id.in_(era_claim_ids)
        ).all()
        for ec in era_claims:
            era_map[ec.claim_id] = ec

    items = []
    for r in records:
        days_old = (today - r.service_date).days if r.service_date else 0
        recoverability = _recoverability_score(r, days_old, fee_map)

        era_info = {}
        if r.era_claim_id and r.era_claim_id in era_map:
            ec = era_map[r.era_claim_id]
            era_info = {
                "cas_group_code": ec.cas_group_code,
                "cas_reason_code": ec.cas_reason_code,
                "cas_adjustment_amount": ec.cas_adjustment_amount,
                "billed_amount_835": ec.billed_amount,
            }

        items.append({
            **r.to_dict(),
            "days_old": days_old,
            "recoverability_score": round(recoverability, 2),
            "denial_status": r.denial_status or "DENIED",
            **era_info,
        })

    if sort_by == "recoverability":
        items.sort(key=lambda x: x["recoverability_score"], reverse=True)
    elif sort_by == "amount":
        items.sort(key=lambda x: x.get("billed_amount_835", 0) or 0, reverse=True)
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
    record = db.session.get(BillingRecord, billing_id)
    if not record:
        return {"error": "Record not found"}
    record.denial_status = "APPEALED"
    db.session.commit()
    return {"status": "appealed", "id": billing_id}


def resolve_denial(billing_id, resolution="RESOLVED", payment_amount=None):
    """Resolve a denied claim. Records outcome for learning (SM-03)."""
    record = db.session.get(BillingRecord, billing_id)
    if not record:
        return {"error": "Record not found"}

    record.denial_status = resolution
    if payment_amount is not None:
        record.total_payment = payment_amount
        record.primary_payment = payment_amount
        record.secondary_payment = 0.0

    # Record denial outcome for learning (SM-03)
    try:
        from app.revenue.denial_memory import record_denial_outcome
        outcome_type = "WRITTEN_OFF" if resolution == "WRITTEN_OFF" else (
            "RECOVERED" if payment_amount and payment_amount > 0 else "WRITTEN_OFF"
        )
        if payment_amount and payment_amount > 0:
            outcome_type = "RECOVERED"
        record_denial_outcome(billing_id, outcome_type, payment_amount or 0.0)
    except Exception:
        pass  # Don't break resolve if learning fails

    db.session.commit()
    return {"status": resolution.lower(), "id": billing_id}


def bulk_appeal(billing_ids):
    """Mark multiple claims as appealed in bulk."""
    if not billing_ids:
        return {"appealed": 0}
    records = BillingRecord.query.filter(
        BillingRecord.id.in_(billing_ids),
        BillingRecord.total_payment == 0,
    ).all()
    count = 0
    for record in records:
        record.denial_status = "APPEALED"
        count += 1
    db.session.commit()
    return {"appealed": count}


def _recoverability_score(record, days_old, fee_map=None):
    """Compute recoverability using smart learning when available (SM-03c)."""
    try:
        from app.revenue.denial_memory import smart_recoverability_score
        return smart_recoverability_score(record, days_old, fee_map)
    except Exception:
        pass

    # Fallback: original formula with pre-loaded fee map
    if fee_map:
        expected = fee_map.get(
            (record.insurance_carrier, record.modality),
            fee_map.get(("_default", record.modality), 500.0)
        )
    else:
        fs = FeeSchedule.query.filter_by(
            payer_code=record.insurance_carrier, modality=record.modality
        ).first()
        if not fs:
            fs = FeeSchedule.query.filter_by(
                payer_code="DEFAULT", modality=record.modality
            ).first()
        expected = fs.expected_rate if fs else 500.0

    return expected * max(0, 1 - (days_old / 365))


def _count_by_status(items):
    counts = {}
    for i in items:
        s = i.get("denial_status", "DENIED")
        counts[s] = counts.get(s, 0) + 1
    return counts
