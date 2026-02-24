"""API endpoints for OCDR Billing Reconciliation System."""

import os
import time
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func, case, extract

from app.models import db, BillingRecord, Payer, FeeSchedule, Physician

api_bp = Blueprint("api", __name__)


@api_bp.route("/health")
def health():
    record_count = BillingRecord.query.count()
    db_path = db.engine.url.database
    db_size = os.path.getsize(db_path) if db_path and os.path.exists(db_path) else 0
    return jsonify({
        "status": "healthy",
        "db_size_bytes": db_size,
        "record_count": record_count,
        "timestamp": datetime.utcnow().isoformat(),
    })


@api_bp.route("/dashboard/stats")
def dashboard_stats():
    """Main dashboard KPI stats."""
    today = date.today()

    total_records = BillingRecord.query.count()
    total_revenue = db.session.query(func.sum(BillingRecord.total_payment)).scalar() or 0

    # Unpaid claims (total_payment = 0)
    unpaid_count = BillingRecord.query.filter(BillingRecord.total_payment == 0).count()
    unpaid_amount = db.session.query(func.count(BillingRecord.id)).filter(
        BillingRecord.total_payment == 0
    ).scalar() or 0

    # Underpayments: compare against fee schedule
    underpayment_data = _get_underpayment_summary()

    # Filing deadline alerts
    deadline_data = _get_filing_deadline_summary(today)

    # Secondary follow-up
    secondary_data = _get_secondary_followup_summary()

    # Denial count
    denial_count = BillingRecord.query.filter(
        BillingRecord.total_payment == 0,
        BillingRecord.denial_status.isnot(None)
    ).count()
    # Also count $0 claims as potential denials
    potential_denials = unpaid_count

    return jsonify({
        "total_records": total_records,
        "total_revenue": round(total_revenue, 2),
        "unpaid_claims": unpaid_count,
        "underpayments": underpayment_data,
        "filing_deadlines": deadline_data,
        "secondary_followup": secondary_data,
        "denial_count": potential_denials,
    })


@api_bp.route("/dashboard/revenue-by-carrier")
def revenue_by_carrier():
    """Revenue grouped by insurance carrier."""
    results = db.session.query(
        BillingRecord.insurance_carrier,
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.count(BillingRecord.id).label("claim_count"),
    ).group_by(BillingRecord.insurance_carrier).order_by(
        func.sum(BillingRecord.total_payment).desc()
    ).all()

    return jsonify([{
        "carrier": r.insurance_carrier,
        "revenue": round(r.revenue, 2),
        "claim_count": r.claim_count,
    } for r in results])


@api_bp.route("/dashboard/revenue-by-month")
def revenue_by_month():
    """Monthly revenue trend."""
    results = db.session.query(
        func.strftime("%Y-%m", BillingRecord.service_date).label("month"),
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.count(BillingRecord.id).label("claim_count"),
    ).group_by(
        func.strftime("%Y-%m", BillingRecord.service_date)
    ).order_by("month").all()

    return jsonify([{
        "month": r.month,
        "revenue": round(r.revenue, 2),
        "claim_count": r.claim_count,
    } for r in results])


@api_bp.route("/dashboard/revenue-by-modality")
def revenue_by_modality():
    """Revenue grouped by imaging modality."""
    results = db.session.query(
        BillingRecord.modality,
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.count(BillingRecord.id).label("claim_count"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
    ).group_by(BillingRecord.modality).order_by(
        func.sum(BillingRecord.total_payment).desc()
    ).all()

    return jsonify([{
        "modality": r.modality,
        "revenue": round(r.revenue, 2),
        "claim_count": r.claim_count,
        "avg_payment": round(r.avg_payment, 2),
    } for r in results])


@api_bp.route("/underpayments")
def underpayments():
    """Underpaid claims list."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    carrier = request.args.get("carrier")
    modality = request.args.get("modality")

    # Get fee schedule as dict
    fee_map = {}
    for fs in FeeSchedule.query.all():
        fee_map[(fs.payer_code, fs.modality)] = fs.expected_rate
        if fs.payer_code == "DEFAULT":
            fee_map.setdefault(("_default", fs.modality), fs.expected_rate)

    query = BillingRecord.query.filter(BillingRecord.total_payment > 0)
    if carrier:
        query = query.filter(BillingRecord.insurance_carrier == carrier)
    if modality:
        query = query.filter(BillingRecord.modality == modality)

    records = query.order_by(BillingRecord.total_payment.asc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    items = []
    for r in records.items:
        expected = fee_map.get(
            (r.insurance_carrier, r.modality),
            fee_map.get(("_default", r.modality), 0)
        )
        # Apply gado premium
        if r.gado_used and r.modality in ("HMRI", "OPEN"):
            expected += 200

        if expected > 0 and r.total_payment < expected * 0.80:
            variance = r.total_payment - expected
            items.append({
                **r.to_dict(),
                "expected_rate": expected,
                "variance": round(variance, 2),
                "pct_of_expected": round(r.total_payment / expected * 100, 1),
            })

    return jsonify({
        "items": items,
        "total": len(items),
        "page": page,
        "per_page": per_page,
    })


@api_bp.route("/underpayments/summary")
def underpayments_summary():
    return jsonify(_get_underpayment_summary())


@api_bp.route("/filing-deadlines")
def filing_deadlines():
    """Filing deadline alerts."""
    status_filter = request.args.get("status")
    today = date.today()

    payer_map = {p.code: p.filing_deadline_days for p in Payer.query.all()}

    query = BillingRecord.query.filter(BillingRecord.total_payment == 0)
    records = query.order_by(BillingRecord.service_date.asc()).all()

    items = []
    for r in records:
        deadline_days = payer_map.get(r.insurance_carrier, 180)
        deadline_date = r.service_date + timedelta(days=deadline_days)
        days_remaining = (deadline_date - today).days

        if days_remaining < 0:
            status = "PAST_DEADLINE"
        elif days_remaining <= 30:
            status = "WARNING"
        else:
            status = "SAFE"

        if status_filter and status != status_filter:
            continue

        items.append({
            **r.to_dict(),
            "deadline_date": deadline_date.isoformat(),
            "days_remaining": days_remaining,
            "status": status,
        })

    # Sort by days remaining ascending
    items.sort(key=lambda x: x["days_remaining"])

    return jsonify({
        "items": items[:200],
        "total": len(items),
        "past_deadline": sum(1 for i in items if i["status"] == "PAST_DEADLINE"),
        "warning": sum(1 for i in items if i["status"] == "WARNING"),
        "safe": sum(1 for i in items if i["status"] == "SAFE"),
    })


@api_bp.route("/filing-deadlines/alerts")
def filing_deadline_alerts():
    today = date.today()
    return jsonify(_get_filing_deadline_summary(today))


@api_bp.route("/denials")
def denials():
    """Denial queue."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    carrier = request.args.get("carrier")
    modality = request.args.get("modality")

    query = BillingRecord.query.filter(BillingRecord.total_payment == 0)
    if carrier:
        query = query.filter(BillingRecord.insurance_carrier == carrier)
    if modality:
        query = query.filter(BillingRecord.modality == modality)

    records = query.order_by(BillingRecord.service_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    today = date.today()
    items = []
    for r in records.items:
        days_old = (today - r.service_date).days if r.service_date else 0
        # Recoverability score: higher for newer, higher-value claims
        fee_map = _get_fee_map()
        expected = fee_map.get(
            (r.insurance_carrier, r.modality),
            fee_map.get(("_default", r.modality), 500)
        )
        recoverability = expected * max(0, 1 - (days_old / 365))
        items.append({
            **r.to_dict(),
            "days_old": days_old,
            "estimated_value": round(expected, 2),
            "recoverability_score": round(recoverability, 2),
            "denial_status": r.denial_status or "DENIED",
        })

    return jsonify({
        "items": items,
        "total": records.total,
        "page": page,
        "pages": records.pages,
    })


@api_bp.route("/secondary-followup")
def secondary_followup():
    """Secondary insurance follow-up queue."""
    payers_with_secondary = [
        p.code for p in Payer.query.filter_by(expected_has_secondary=True).all()
    ]

    records = BillingRecord.query.filter(
        BillingRecord.primary_payment > 0,
        BillingRecord.secondary_payment == 0,
        BillingRecord.insurance_carrier.in_(payers_with_secondary),
    ).order_by(BillingRecord.primary_payment.desc()).limit(500).all()

    total_estimated = sum(r.primary_payment * 0.20 for r in records)  # ~20% secondary

    return jsonify({
        "items": [r.to_dict() for r in records],
        "total": len(records),
        "estimated_recovery": round(total_estimated, 2),
    })


@api_bp.route("/payer-monitor")
def payer_monitor():
    """Payer contract monitoring."""
    results = db.session.query(
        BillingRecord.insurance_carrier,
        func.strftime("%Y-%m", BillingRecord.service_date).label("month"),
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.count(BillingRecord.id).label("volume"),
    ).group_by(
        BillingRecord.insurance_carrier,
        func.strftime("%Y-%m", BillingRecord.service_date),
    ).order_by(BillingRecord.insurance_carrier, "month").all()

    # Build per-carrier monthly data
    carrier_data = {}
    for r in results:
        if r.insurance_carrier not in carrier_data:
            carrier_data[r.insurance_carrier] = []
        carrier_data[r.insurance_carrier].append({
            "month": r.month,
            "revenue": round(r.revenue, 2),
            "volume": r.volume,
        })

    # Calculate alerts
    alerts = []
    for carrier, months in carrier_data.items():
        if len(months) >= 4:
            recent = months[-1]
            prior_avg_rev = sum(m["revenue"] for m in months[-4:-1]) / 3
            prior_avg_vol = sum(m["volume"] for m in months[-4:-1]) / 3

            if prior_avg_rev > 0:
                rev_change = (recent["revenue"] - prior_avg_rev) / prior_avg_rev
                vol_change = (recent["volume"] - prior_avg_vol) / prior_avg_vol if prior_avg_vol > 0 else 0

                if rev_change < -0.25:
                    severity = "critical" if rev_change < -0.50 else "warning"
                    alerts.append({
                        "carrier": carrier,
                        "severity": severity,
                        "revenue_change_pct": round(rev_change * 100, 1),
                        "volume_change_pct": round(vol_change * 100, 1),
                        "current_revenue": recent["revenue"],
                        "prior_avg_revenue": round(prior_avg_rev, 2),
                    })

    alerts.sort(key=lambda x: x["revenue_change_pct"])

    return jsonify({
        "carrier_data": carrier_data,
        "alerts": alerts,
    })


@api_bp.route("/physicians")
def physicians():
    """Physician revenue rankings."""
    limit = request.args.get("limit", 30, type=int)

    results = db.session.query(
        BillingRecord.referring_doctor,
        func.sum(BillingRecord.total_payment).label("revenue"),
        func.count(BillingRecord.id).label("claim_count"),
        func.avg(BillingRecord.total_payment).label("avg_payment"),
    ).group_by(BillingRecord.referring_doctor).order_by(
        func.sum(BillingRecord.total_payment).desc()
    ).limit(limit).all()

    total_revenue = db.session.query(func.sum(BillingRecord.total_payment)).scalar() or 1

    return jsonify([{
        "name": r.referring_doctor,
        "revenue": round(r.revenue, 2),
        "claim_count": r.claim_count,
        "avg_payment": round(r.avg_payment, 2),
        "pct_of_total": round(r.revenue / total_revenue * 100, 1),
    } for r in results])


@api_bp.route("/duplicates")
def duplicates():
    """Potential duplicate claims."""
    dupes = db.session.query(
        BillingRecord.patient_name,
        BillingRecord.service_date,
        BillingRecord.scan_type,
        BillingRecord.modality,
        func.count(BillingRecord.id).label("count"),
    ).group_by(
        BillingRecord.patient_name,
        BillingRecord.service_date,
        BillingRecord.scan_type,
        BillingRecord.modality,
    ).having(func.count(BillingRecord.id) > 1).all()

    items = []
    for d in dupes:
        # Skip C.A.P exceptions
        records = BillingRecord.query.filter_by(
            patient_name=d.patient_name,
            service_date=d.service_date,
            scan_type=d.scan_type,
            modality=d.modality,
        ).all()
        is_cap = any(
            r.description and "C.A.P" in r.description.upper() for r in records
        )
        if not is_cap:
            items.append({
                "patient_name": d.patient_name,
                "service_date": d.service_date.isoformat() if d.service_date else None,
                "scan_type": d.scan_type,
                "modality": d.modality,
                "count": d.count,
            })

    return jsonify({"items": items, "total": len(items)})


# --- Helper functions ---

def _get_fee_map():
    fee_map = {}
    for fs in FeeSchedule.query.all():
        fee_map[(fs.payer_code, fs.modality)] = fs.expected_rate
        if fs.payer_code == "DEFAULT":
            fee_map[("_default", fs.modality)] = fs.expected_rate
    return fee_map


def _get_underpayment_summary():
    fee_map = _get_fee_map()
    paid_records = BillingRecord.query.filter(BillingRecord.total_payment > 0).all()

    total_flagged = 0
    total_variance = 0.0
    by_carrier = {}
    by_modality = {}

    for r in paid_records:
        expected = fee_map.get(
            (r.insurance_carrier, r.modality),
            fee_map.get(("_default", r.modality), 0)
        )
        if r.gado_used and r.modality in ("HMRI", "OPEN"):
            expected += 200

        if expected > 0 and r.total_payment < expected * 0.80:
            total_flagged += 1
            variance = r.total_payment - expected
            total_variance += variance

            carrier = r.insurance_carrier
            by_carrier[carrier] = by_carrier.get(carrier, 0) + variance

            mod = r.modality
            by_modality[mod] = by_modality.get(mod, 0) + variance

    return {
        "total_flagged": total_flagged,
        "total_variance": round(abs(total_variance), 2),
        "by_carrier": [
            {"carrier": k, "variance": round(abs(v), 2)}
            for k, v in sorted(by_carrier.items(), key=lambda x: x[1])[:10]
        ],
        "by_modality": [
            {"modality": k, "variance": round(abs(v), 2)}
            for k, v in sorted(by_modality.items(), key=lambda x: x[1])[:10]
        ],
    }


def _get_filing_deadline_summary(today):
    payer_map = {p.code: p.filing_deadline_days for p in Payer.query.all()}
    unpaid = BillingRecord.query.filter(BillingRecord.total_payment == 0).all()

    past_deadline = 0
    warning = 0
    for r in unpaid:
        deadline_days = payer_map.get(r.insurance_carrier, 180)
        deadline_date = r.service_date + timedelta(days=deadline_days)
        days_remaining = (deadline_date - today).days
        if days_remaining < 0:
            past_deadline += 1
        elif days_remaining <= 30:
            warning += 1

    return {
        "past_deadline": past_deadline,
        "warning": warning,
        "total_unpaid": len(unpaid),
    }


def _get_secondary_followup_summary():
    payers_with_secondary = [
        p.code for p in Payer.query.filter_by(expected_has_secondary=True).all()
    ]
    count = BillingRecord.query.filter(
        BillingRecord.primary_payment > 0,
        BillingRecord.secondary_payment == 0,
        BillingRecord.insurance_carrier.in_(payers_with_secondary),
    ).count()

    estimated = db.session.query(
        func.sum(BillingRecord.primary_payment * 0.20)
    ).filter(
        BillingRecord.primary_payment > 0,
        BillingRecord.secondary_payment == 0,
        BillingRecord.insurance_carrier.in_(payers_with_secondary),
    ).scalar() or 0

    return {
        "count": count,
        "estimated_recovery": round(estimated, 2),
    }
