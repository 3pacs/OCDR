"""API endpoints for OCDR Billing Reconciliation System."""

import os
import time
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func, case, extract

from app.models import db, BillingRecord, Payer, FeeSchedule, Physician, ScheduleRecord

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


@api_bp.route("/schedule/stats")
def schedule_stats():
    """Schedule KPI summary."""
    today = date.today()

    total = ScheduleRecord.query.count()
    upcoming = ScheduleRecord.query.filter(ScheduleRecord.scheduled_date >= today).count()
    past = ScheduleRecord.query.filter(ScheduleRecord.scheduled_date < today).count()
    completed = ScheduleRecord.query.filter_by(status="COMPLETED").count()
    cancelled = ScheduleRecord.query.filter_by(status="CANCELLED").count()
    no_show = ScheduleRecord.query.filter_by(status="NO_SHOW").count()

    # Counts by modality group
    mri_total = ScheduleRecord.query.filter(
        ScheduleRecord.modality.in_(["MRI", "HMRI", "OPEN"])
    ).count()
    ct_pet_total = ScheduleRecord.query.filter(
        ScheduleRecord.modality.in_(["CT", "PET"])
    ).count()
    mri_upcoming = ScheduleRecord.query.filter(
        ScheduleRecord.modality.in_(["MRI", "HMRI", "OPEN"]),
        ScheduleRecord.scheduled_date >= today,
    ).count()
    ct_pet_upcoming = ScheduleRecord.query.filter(
        ScheduleRecord.modality.in_(["CT", "PET"]),
        ScheduleRecord.scheduled_date >= today,
    ).count()

    return jsonify({
        "total": total,
        "upcoming": upcoming,
        "past": past,
        "completed": completed,
        "cancelled": cancelled,
        "no_show": no_show,
        "mri_total": mri_total,
        "ct_pet_total": ct_pet_total,
        "mri_upcoming": mri_upcoming,
        "ct_pet_upcoming": ct_pet_upcoming,
    })


@api_bp.route("/schedule/list")
def schedule_list():
    """Paginated schedule records with filters."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    modality_group = request.args.get("modality_group")  # mri or ct_pet
    time_range = request.args.get("time_range")  # past, future, all
    status_filter = request.args.get("status")
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = ScheduleRecord.query
    today = date.today()

    if modality_group == "mri":
        query = query.filter(ScheduleRecord.modality.in_(["MRI", "HMRI", "OPEN"]))
    elif modality_group == "ct_pet":
        query = query.filter(ScheduleRecord.modality.in_(["CT", "PET"]))

    if time_range == "past":
        query = query.filter(ScheduleRecord.scheduled_date < today)
    elif time_range == "future":
        query = query.filter(ScheduleRecord.scheduled_date >= today)

    if status_filter:
        query = query.filter(ScheduleRecord.status == status_filter.upper())

    if start_date:
        try:
            query = query.filter(ScheduleRecord.scheduled_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if end_date:
        try:
            query = query.filter(ScheduleRecord.scheduled_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
        except ValueError:
            pass

    records = query.order_by(ScheduleRecord.scheduled_date.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "items": [r.to_dict() for r in records.items],
        "total": records.total,
        "page": page,
        "pages": records.pages,
    })


@api_bp.route("/schedule/by-month")
def schedule_by_month():
    """Monthly schedule volume broken down by modality group."""
    results = db.session.query(
        func.strftime("%Y-%m", ScheduleRecord.scheduled_date).label("month"),
        ScheduleRecord.modality,
        func.count(ScheduleRecord.id).label("count"),
    ).group_by(
        func.strftime("%Y-%m", ScheduleRecord.scheduled_date),
        ScheduleRecord.modality,
    ).order_by("month").all()

    # Group into MRI vs CT/PET per month
    months = {}
    for r in results:
        if r.month not in months:
            months[r.month] = {"month": r.month, "mri": 0, "ct_pet": 0, "other": 0}
        if r.modality in ("MRI", "HMRI", "OPEN"):
            months[r.month]["mri"] += r.count
        elif r.modality in ("CT", "PET"):
            months[r.month]["ct_pet"] += r.count
        else:
            months[r.month]["other"] += r.count

    return jsonify(sorted(months.values(), key=lambda x: x["month"]))


@api_bp.route("/schedule/by-day")
def schedule_by_day():
    """Daily schedule counts for calendar heatmap view. Accepts start/end date params."""
    start_date = request.args.get("start_date")
    end_date = request.args.get("end_date")

    query = db.session.query(
        ScheduleRecord.scheduled_date,
        ScheduleRecord.modality,
        func.count(ScheduleRecord.id).label("count"),
    )

    if start_date:
        try:
            query = query.filter(ScheduleRecord.scheduled_date >= datetime.strptime(start_date, "%Y-%m-%d").date())
        except ValueError:
            pass
    if end_date:
        try:
            query = query.filter(ScheduleRecord.scheduled_date <= datetime.strptime(end_date, "%Y-%m-%d").date())
        except ValueError:
            pass

    results = query.group_by(
        ScheduleRecord.scheduled_date, ScheduleRecord.modality
    ).all()

    days = {}
    for r in results:
        d = r.scheduled_date.isoformat()
        if d not in days:
            days[d] = {"date": d, "mri": 0, "ct_pet": 0, "total": 0}
        if r.modality in ("MRI", "HMRI", "OPEN"):
            days[d]["mri"] += r.count
        elif r.modality in ("CT", "PET"):
            days[d]["ct_pet"] += r.count
        days[d]["total"] += r.count

    return jsonify(sorted(days.values(), key=lambda x: x["date"]))


@api_bp.route("/schedule/by-status")
def schedule_by_status():
    """Schedule status breakdown."""
    results = db.session.query(
        ScheduleRecord.status,
        func.count(ScheduleRecord.id).label("count"),
    ).group_by(ScheduleRecord.status).all()

    return jsonify([{"status": r.status, "count": r.count} for r in results])


@api_bp.route("/schedule/by-doctor")
def schedule_by_doctor():
    """Top referring doctors by scheduled scan volume."""
    results = db.session.query(
        ScheduleRecord.referring_doctor,
        func.count(ScheduleRecord.id).label("count"),
    ).filter(
        ScheduleRecord.referring_doctor.isnot(None),
        ScheduleRecord.referring_doctor != "",
    ).group_by(
        ScheduleRecord.referring_doctor
    ).order_by(func.count(ScheduleRecord.id).desc()).limit(15).all()

    return jsonify([{"doctor": r.referring_doctor, "count": r.count} for r in results])


@api_bp.route("/schedule/import", methods=["POST"])
def schedule_import():
    """Trigger import from the configured schedule folder."""
    from flask import current_app
    from app.import_engine.schedule_importer import import_folder

    folder = current_app.config.get("SCHEDULE_FOLDER")
    if not folder:
        return jsonify({"error": "SCHEDULE_FOLDER not configured"}), 400

    results = import_folder(folder)
    return jsonify(results)


@api_bp.route("/schedule/import/config")
def schedule_import_config():
    """Return current schedule import folder path."""
    from flask import current_app
    folder = current_app.config.get("SCHEDULE_FOLDER", "")
    exists = os.path.isdir(folder)
    file_count = 0
    if exists:
        file_count = sum(
            1 for f in os.listdir(folder)
            if os.path.isfile(os.path.join(folder, f)) and
            os.path.splitext(f)[1].lower() in (".csv", ".xlsx", ".xls")
        )
    return jsonify({
        "folder": folder,
        "exists": exists,
        "pending_files": file_count,
    })


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
