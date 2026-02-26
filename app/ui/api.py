"""API endpoints for OCDR Billing Reconciliation System."""

import os
import time
from datetime import date, datetime, timedelta

from flask import Blueprint, jsonify, request
from sqlalchemy import func, case, extract

from app.models import db, BillingRecord, Payer, FeeSchedule, Physician, ScheduleRecord, EraPayment, EraClaimLine

api_bp = Blueprint("api", __name__)


@api_bp.route("/health")
def health():
    record_count = BillingRecord.query.count()
    try:
        db_path = db.engine.url.database
        db_size = os.path.getsize(db_path) if db_path and os.path.exists(str(db_path)) else 0
    except Exception:
        db_size = 0
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

    # Smart insights for the dashboard
    try:
        from app.analytics.smart_insights import generate_insights, forecast_revenue
        insights = generate_insights()
        forecast = forecast_revenue(months_ahead=3)
    except Exception:
        insights = []
        forecast = {"status": "unavailable", "forecast": []}

    return jsonify({
        "total_records": total_records,
        "total_revenue": round(total_revenue, 2),
        "unpaid_claims": unpaid_count,
        "underpayments": underpayment_data,
        "filing_deadlines": deadline_data,
        "secondary_followup": secondary_data,
        "denial_count": potential_denials,
        "insights": insights,
        "forecast": forecast,
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
    if folder and not os.path.isdir(folder):
        try:
            os.makedirs(folder, exist_ok=True)
        except OSError:
            pass
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


# ══════════════════════════════════════════════════════════════════
#  835 ERA Upload & Parsing
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/era/upload", methods=["POST"])
def era_upload():
    """Upload and parse one or more 835 EDI files.

    Accepts multipart/form-data with field name 'files'.
    Parses each file, stores EraPayment + EraClaimLine records.
    Returns per-file results summary.
    """
    from flask import current_app
    from werkzeug.utils import secure_filename
    from app.parser.era_835_parser import parse_835

    if "files" not in request.files:
        return jsonify({"error": "No files provided. Use field name 'files'."}), 400

    files = request.files.getlist("files")
    if not files or all(f.filename == "" for f in files):
        return jsonify({"error": "No files selected"}), 400

    # Ensure upload dir exists
    upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), "835")
    os.makedirs(upload_dir, exist_ok=True)

    results = []
    total_payments = 0
    total_claims = 0

    for f in files:
        filename = secure_filename(f.filename)
        if not filename:
            continue

        # Save to disk
        filepath = os.path.join(upload_dir, filename)
        f.save(filepath)

        # Parse
        with open(filepath, "r", encoding="utf-8", errors="replace") as fh:
            raw_text = fh.read()
        parsed = parse_835(raw_text, filename=filename)

        if parsed["errors"]:
            results.append({
                "filename": filename,
                "status": "error",
                "errors": parsed["errors"],
                "payments": 0,
                "claims": 0,
            })
            continue

        # Check for duplicate file upload
        existing_upload = EraPayment.query.filter_by(filename=filename).first()
        if existing_upload:
            results.append({
                "filename": filename,
                "status": "skipped",
                "errors": [f"File already uploaded (payment ID {existing_upload.id})"],
                "payments": 0,
                "claims": 0,
            })
            continue

        # Store EraPayment
        payment_info = parsed["payment"]
        era_payment = EraPayment(
            filename=filename,
            check_eft_number=payment_info.get("check_eft_number"),
            payment_amount=payment_info.get("payment_amount", 0.0),
            payment_date=payment_info.get("payment_date"),
            payment_method=payment_info.get("payment_method"),
            payer_name=payment_info.get("payer_name"),
        )
        db.session.add(era_payment)
        db.session.flush()

        # Store EraClaimLines
        claim_count = 0
        payment_date = payment_info.get("payment_date")  # fallback date

        for claim in parsed["claims"]:
            # Collect CPT codes and adjustments from service lines
            cpt_codes = []
            all_adjustments = list(claim.get("adjustments", []))
            for svc in claim.get("service_lines", []):
                if svc.get("cpt_code"):
                    cpt_codes.append(svc["cpt_code"])
                all_adjustments.extend(svc.get("adjustments", []))

            # Aggregate all unique group codes and reason codes
            group_codes = sorted(set(a.get("group_code", "") for a in all_adjustments if a.get("group_code")))
            reason_codes = sorted(set(a.get("reason_code", "") for a in all_adjustments if a.get("reason_code")))
            total_adj_amount = sum(a.get("amount", 0) for a in all_adjustments)

            # Use service_date from claim, fall back to payment date
            service_date = claim.get("service_date") or payment_date

            era_claim = EraClaimLine(
                era_payment_id=era_payment.id,
                claim_id=claim.get("claim_id"),
                claim_status=claim.get("claim_status"),
                billed_amount=claim.get("billed_amount", 0.0),
                paid_amount=claim.get("paid_amount", 0.0),
                patient_name_835=claim.get("patient_name"),
                service_date_835=service_date,
                cpt_code=", ".join(cpt_codes) if cpt_codes else None,
                cas_group_code=", ".join(group_codes) if group_codes else None,
                cas_reason_code=", ".join(reason_codes) if reason_codes else None,
                cas_adjustment_amount=total_adj_amount if total_adj_amount else None,
            )
            db.session.add(era_claim)
            claim_count += 1

        db.session.commit()
        total_payments += 1
        total_claims += claim_count

        results.append({
            "filename": filename,
            "status": "success",
            "payment_id": era_payment.id,
            "payer": payment_info.get("payer_name"),
            "check_number": payment_info.get("check_eft_number"),
            "payment_amount": payment_info.get("payment_amount", 0.0),
            "payment_date": payment_info.get("payment_date").isoformat() if payment_info.get("payment_date") else None,
            "claims": claim_count,
            "errors": [],
        })

    return jsonify({
        "results": results,
        "total_files": len(results),
        "total_payments": total_payments,
        "total_claims": total_claims,
    })


@api_bp.route("/era/payments")
def era_payments():
    """List all ERA payments with pagination."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    payer = request.args.get("payer")

    query = EraPayment.query
    if payer:
        query = query.filter(EraPayment.payer_name.ilike(f"%{payer}%"))

    payments = query.order_by(EraPayment.parsed_at.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "items": [p.to_dict() for p in payments.items],
        "total": payments.total,
        "page": page,
        "pages": payments.pages,
    })


@api_bp.route("/era/payments/<int:payment_id>")
def era_payment_detail(payment_id):
    """Get a single ERA payment with all its claim lines."""
    payment = EraPayment.query.get_or_404(payment_id)
    claims = EraClaimLine.query.filter_by(era_payment_id=payment_id).order_by(
        EraClaimLine.paid_amount.desc()
    ).all()

    return jsonify({
        "payment": payment.to_dict(),
        "claims": [c.to_dict() for c in claims],
    })


@api_bp.route("/era/claims")
def era_claims():
    """List all ERA claim lines with pagination and filters."""
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    patient = request.args.get("patient")
    status = request.args.get("status")
    payment_id = request.args.get("payment_id", type=int)

    query = EraClaimLine.query
    if patient:
        query = query.filter(EraClaimLine.patient_name_835.ilike(f"%{patient}%"))
    if status:
        query = query.filter(EraClaimLine.claim_status.ilike(f"%{status}%"))
    if payment_id:
        query = query.filter(EraClaimLine.era_payment_id == payment_id)

    claims = query.order_by(EraClaimLine.id.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return jsonify({
        "items": [c.to_dict() for c in claims.items],
        "total": claims.total,
        "page": page,
        "pages": claims.pages,
    })


@api_bp.route("/era/stats")
def era_stats():
    """ERA parsing summary stats."""
    total_payments = EraPayment.query.count()
    total_claims = EraClaimLine.query.count()
    total_paid = db.session.query(func.sum(EraPayment.payment_amount)).scalar() or 0
    total_billed = db.session.query(func.sum(EraClaimLine.billed_amount)).scalar() or 0
    total_claim_paid = db.session.query(func.sum(EraClaimLine.paid_amount)).scalar() or 0
    denied_count = EraClaimLine.query.filter(
        EraClaimLine.claim_status.ilike("%DENIED%")
    ).count()
    adjustment_total = db.session.query(
        func.sum(EraClaimLine.cas_adjustment_amount)
    ).scalar() or 0

    # By payer
    by_payer = db.session.query(
        EraPayment.payer_name,
        func.sum(EraPayment.payment_amount).label("total"),
        func.count(EraPayment.id).label("count"),
    ).group_by(EraPayment.payer_name).order_by(
        func.sum(EraPayment.payment_amount).desc()
    ).limit(10).all()

    # By payment method
    by_method = db.session.query(
        EraPayment.payment_method,
        func.count(EraPayment.id).label("count"),
        func.sum(EraPayment.payment_amount).label("total"),
    ).group_by(EraPayment.payment_method).all()

    return jsonify({
        "total_payments": total_payments,
        "total_claims": total_claims,
        "total_paid": round(total_paid, 2),
        "total_billed": round(total_billed, 2),
        "total_claim_paid": round(total_claim_paid, 2),
        "denied_count": denied_count,
        "adjustment_total": round(adjustment_total, 2),
        "by_payer": [{"payer": r.payer_name, "total": round(r.total, 2), "count": r.count} for r in by_payer],
        "by_method": [{"method": r.payment_method, "count": r.count, "total": round(r.total or 0, 2)} for r in by_method],
    })


@api_bp.route("/era/by-month")
def era_by_month():
    """ERA payments aggregated by month."""
    results = db.session.query(
        func.strftime("%Y-%m", EraPayment.payment_date).label("month"),
        func.sum(EraPayment.payment_amount).label("total"),
        func.count(EraPayment.id).label("count"),
    ).filter(
        EraPayment.payment_date.isnot(None)
    ).group_by(
        func.strftime("%Y-%m", EraPayment.payment_date)
    ).order_by("month").all()

    return jsonify([{
        "month": r.month,
        "total": round(r.total, 2),
        "count": r.count,
    } for r in results])


# ══════════════════════════════════════════════════════════════════
#  F-01: Excel Import
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/import/excel", methods=["POST"])
def import_excel():
    """Upload and import billing data from an Excel workbook."""
    from flask import current_app
    from werkzeug.utils import secure_filename
    from app.import_engine.excel_importer import import_excel as do_import

    if "file" not in request.files:
        return jsonify({"error": "No file provided. Use field name 'file'."}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(f.filename)
    upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), "excel")
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    f.save(filepath)

    sheet_name = request.form.get("sheet")
    result = do_import(filepath, sheet_name=sheet_name)

    # Auto-learn fee schedules from imported payment data
    if result.get("imported", 0) > 0:
        try:
            from app.revenue.payment_patterns import suggest_fee_updates, apply_fee_update
            for s in suggest_fee_updates(min_count=10):
                if s["direction"] == "NEW":
                    apply_fee_update(s["carrier"], s["modality"], s["suggested_rate"])
        except Exception:
            pass

    return jsonify(result)


@api_bp.route("/import/csv", methods=["POST"])
def import_csv_endpoint():
    """Upload and import data from a CSV file."""
    from flask import current_app
    from werkzeug.utils import secure_filename
    from app.import_engine.csv_importer import import_csv

    if "file" not in request.files:
        return jsonify({"error": "No file provided. Use field name 'file'."}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(f.filename)
    upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), "csv")
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    f.save(filepath)

    result = import_csv(filepath)

    # Auto-learn fee schedules from imported payment data
    if result.get("imported", 0) > 0:
        try:
            from app.revenue.payment_patterns import suggest_fee_updates, apply_fee_update
            for s in suggest_fee_updates(min_count=10):
                if s["direction"] == "NEW":
                    apply_fee_update(s["carrier"], s["modality"], s["suggested_rate"])
        except Exception:
            pass

    return jsonify(result)


@api_bp.route("/import/pdf", methods=["POST"])
def import_pdf_endpoint():
    """Upload and import billing data from a PDF file."""
    from flask import current_app
    from werkzeug.utils import secure_filename
    from app.import_engine.pdf_importer import import_pdf

    if "file" not in request.files:
        return jsonify({"error": "No file provided. Use field name 'file'."}), 400

    f = request.files["file"]
    if not f.filename:
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(f.filename)
    upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), "pdf")
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    f.save(filepath)

    result = import_pdf(filepath)
    return jsonify(result)


@api_bp.route("/import/status")
def import_status():
    """Get import statistics and history."""
    total_billing = BillingRecord.query.count()
    total_schedule = ScheduleRecord.query.count()
    total_era = EraPayment.query.count()

    # By import source
    by_source = db.session.query(
        BillingRecord.import_source,
        func.count(BillingRecord.id).label("count"),
    ).group_by(BillingRecord.import_source).all()

    return jsonify({
        "total_billing_records": total_billing,
        "total_schedule_records": total_schedule,
        "total_era_payments": total_era,
        "by_source": [{"source": r.import_source or "UNKNOWN", "count": r.count} for r in by_source],
    })


# ══════════════════════════════════════════════════════════════════
#  F-03: Auto-Match Engine
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/match/run", methods=["POST"])
def match_run():
    """Run the auto-match engine on unmatched ERA claim lines."""
    from app.matching.match_engine import run_matching
    threshold_accept = request.json.get("auto_accept", 0.95) if request.is_json else 0.95
    threshold_review = request.json.get("review", 0.80) if request.is_json else 0.80
    result = run_matching(
        auto_accept_threshold=threshold_accept,
        review_threshold=threshold_review,
    )
    return jsonify(result)


@api_bp.route("/match/results")
def match_results():
    """Get match results with optional status filter."""
    from app.matching.match_engine import get_match_results
    status = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    return jsonify(get_match_results(status_filter=status, page=page, per_page=per_page))


@api_bp.route("/match/confirm/<int:claim_id>", methods=["POST"])
def match_confirm(claim_id):
    """Confirm or reassign a match."""
    from app.matching.match_engine import confirm_match
    billing_id = request.json.get("billing_id") if request.is_json else None
    return jsonify(confirm_match(claim_id, billing_id))


@api_bp.route("/match/reject/<int:claim_id>", methods=["POST"])
def match_reject(claim_id):
    """Reject a match."""
    from app.matching.match_engine import reject_match
    return jsonify(reject_match(claim_id))


# ══════════════════════════════════════════════════════════════════
#  F-04: Denial Tracking & Appeal Queue
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/denials/queue")
def denial_queue():
    """Get prioritized denial queue."""
    from app.revenue.denial_tracker import get_denial_queue
    carrier = request.args.get("carrier")
    modality = request.args.get("modality")
    status = request.args.get("status")
    sort_by = request.args.get("sort", "recoverability")
    page = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 50, type=int)
    return jsonify(get_denial_queue(
        carrier=carrier, modality=modality, status_filter=status,
        sort_by=sort_by, page=page, per_page=per_page,
    ))


@api_bp.route("/denials/<int:billing_id>/appeal", methods=["POST"])
def denial_appeal(billing_id):
    """Mark a claim as appealed."""
    from app.revenue.denial_tracker import appeal_denial
    return jsonify(appeal_denial(billing_id))


@api_bp.route("/denials/<int:billing_id>/resolve", methods=["POST"])
def denial_resolve(billing_id):
    """Resolve a denied claim."""
    from app.revenue.denial_tracker import resolve_denial
    resolution = "RESOLVED"
    payment = None
    if request.is_json:
        resolution = request.json.get("resolution", "RESOLVED")
        payment = request.json.get("payment_amount")
    return jsonify(resolve_denial(billing_id, resolution=resolution, payment_amount=payment))


@api_bp.route("/denials/bulk-appeal", methods=["POST"])
def denial_bulk_appeal():
    """Bulk mark claims as appealed."""
    from app.revenue.denial_tracker import bulk_appeal
    ids = request.json.get("ids", []) if request.is_json else []
    return jsonify(bulk_appeal(ids))


# ══════════════════════════════════════════════════════════════════
#  F-10: Physician Statements
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/statements")
def statements_list():
    """List physician statements."""
    from app.revenue.physician_statements import list_statements
    physician = request.args.get("physician")
    status = request.args.get("status")
    page = request.args.get("page", 1, type=int)
    return jsonify(list_statements(physician=physician, status=status, page=page))


@api_bp.route("/statements/generate", methods=["POST"])
def statements_generate():
    """Generate a physician statement."""
    from app.revenue.physician_statements import generate_statement
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400
    physician = request.json.get("physician_name")
    year = request.json.get("year", date.today().year)
    month = request.json.get("month", date.today().month)
    if not physician:
        return jsonify({"error": "physician_name required"}), 400
    return jsonify(generate_statement(physician, year, month))


@api_bp.route("/statements/<int:statement_id>/pay", methods=["POST"])
def statements_pay(statement_id):
    """Record a payment against a statement."""
    from app.revenue.physician_statements import record_payment
    amount = request.json.get("amount", 0) if request.is_json else 0
    return jsonify(record_payment(statement_id, amount))


@api_bp.route("/statements/<int:statement_id>/html")
def statements_html(statement_id):
    """Get statement as HTML (for PDF rendering)."""
    from app.revenue.physician_statements import generate_statement, generate_statement_html
    from app.models import PhysicianStatement
    stmt = PhysicianStatement.query.get_or_404(statement_id)
    data = generate_statement(stmt.physician_name,
                              int(stmt.statement_period[:4]),
                              int(stmt.statement_period[5:7]))
    html = generate_statement_html(data)
    return html, 200, {"Content-Type": "text/html"}


# ══════════════════════════════════════════════════════════════════
#  F-11: Folder Monitor
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/monitor/start", methods=["POST"])
def monitor_start():
    """Start the folder monitor."""
    from flask import current_app
    from app.monitor.folder_watcher import start_monitor
    interval = request.json.get("interval", 30) if request.is_json else 30
    return jsonify(start_monitor(current_app._get_current_object(), interval=interval))


@api_bp.route("/monitor/stop", methods=["POST"])
def monitor_stop():
    """Stop the folder monitor."""
    from app.monitor.folder_watcher import stop_monitor
    return jsonify(stop_monitor())


@api_bp.route("/monitor/status")
def monitor_status():
    """Get folder monitor status."""
    from app.monitor.folder_watcher import get_monitor_status
    return jsonify(get_monitor_status())


@api_bp.route("/monitor/scan", methods=["POST"])
def monitor_scan():
    """Run a single manual scan."""
    from flask import current_app
    from app.monitor.folder_watcher import scan_once
    return jsonify(scan_once(current_app._get_current_object()))


# ══════════════════════════════════════════════════════════════════
#  F-13: PSMA PET Tracking
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/psma")
def psma_summary():
    """PSMA PET tracking summary."""
    from app.analytics.psma_tracker import get_psma_summary
    return jsonify(get_psma_summary())


@api_bp.route("/psma/by-year")
def psma_by_year():
    """PSMA volume by year."""
    from app.analytics.psma_tracker import get_psma_by_year
    return jsonify(get_psma_by_year())


@api_bp.route("/psma/by-physician")
def psma_by_physician():
    """PSMA by referring physician."""
    from app.analytics.psma_tracker import get_psma_by_physician
    return jsonify(get_psma_by_physician())


@api_bp.route("/psma/by-carrier")
def psma_by_carrier():
    """PSMA by insurance carrier."""
    from app.analytics.psma_tracker import get_psma_by_carrier
    return jsonify(get_psma_by_carrier())


# ══════════════════════════════════════════════════════════════════
#  F-14: Gado Contrast Tracking
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/gado")
def gado_summary():
    """Gado contrast usage summary."""
    from app.analytics.gado_tracker import get_gado_summary
    cost = request.args.get("cost_per_dose", type=float)
    return jsonify(get_gado_summary(cost_per_dose=cost))


@api_bp.route("/gado/by-year")
def gado_by_year():
    """Gado usage by year."""
    from app.analytics.gado_tracker import get_gado_by_year
    cost = request.args.get("cost_per_dose", type=float)
    return jsonify(get_gado_by_year(cost_per_dose=cost))


@api_bp.route("/gado/by-physician")
def gado_by_physician():
    """Gado usage by physician."""
    from app.analytics.gado_tracker import get_gado_by_physician
    return jsonify(get_gado_by_physician())


@api_bp.route("/gado/margin")
def gado_margin():
    """Gado margin analysis by carrier."""
    from app.analytics.gado_tracker import get_gado_margin_analysis
    cost = request.args.get("cost_per_dose", type=float)
    return jsonify(get_gado_margin_analysis(cost_per_dose=cost))


# ══════════════════════════════════════════════════════════════════
#  F-16: Denial Reason Code Analytics
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/denial-analytics")
def denial_analytics():
    """Denial reason code analytics."""
    from app.analytics.denial_analytics import get_denial_analytics
    return jsonify(get_denial_analytics())


@api_bp.route("/denial-analytics/pareto")
def denial_pareto():
    """Denial reason code Pareto analysis."""
    from app.analytics.denial_analytics import get_denial_pareto
    return jsonify(get_denial_pareto())


@api_bp.route("/denial-analytics/by-carrier")
def denial_by_carrier():
    """Denial codes by carrier."""
    from app.analytics.denial_analytics import get_denials_by_carrier
    return jsonify(get_denials_by_carrier())


@api_bp.route("/denial-analytics/trend")
def denial_trend():
    """Denial reason code trend over time."""
    from app.analytics.denial_analytics import get_denial_trend
    return jsonify(get_denial_trend())


# ══════════════════════════════════════════════════════════════════
#  F-17: Check/EFT Payment Matching
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/payments")
def payments_list():
    """List ERA payments for reconciliation."""
    from app.core.payment_matching import get_payment_summary
    return jsonify(get_payment_summary())


@api_bp.route("/payments/<check_number>")
def payment_by_check(check_number):
    """Get all claims under a check/EFT number."""
    from app.core.payment_matching import get_payment_detail
    return jsonify(get_payment_detail(check_number))


@api_bp.route("/payments/reconcile", methods=["POST"])
def payments_reconcile():
    """Import bank statement and reconcile against ERA payments."""
    from flask import current_app
    from werkzeug.utils import secure_filename
    from app.core.payment_matching import import_bank_statement

    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400
    f = request.files["file"]
    filename = secure_filename(f.filename)
    upload_dir = os.path.join(current_app.config.get("UPLOAD_FOLDER", "uploads"), "bank")
    os.makedirs(upload_dir, exist_ok=True)
    filepath = os.path.join(upload_dir, filename)
    f.save(filepath)
    return jsonify(import_bank_statement(filepath))


@api_bp.route("/payments/status")
def payments_reconciliation_status():
    """Get overall reconciliation status."""
    from app.core.payment_matching import get_reconciliation_status
    return jsonify(get_reconciliation_status())


# ══════════════════════════════════════════════════════════════════
#  F-18: CSV Export
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/export/csv")
def export_csv():
    """Export billing records to CSV."""
    from flask import current_app, send_file
    from app.export.csv_exporter import export_billing_csv
    result = export_billing_csv(app=current_app)
    return send_file(result["filepath"], as_attachment=True,
                     download_name="master_data.csv", mimetype="text/csv")


@api_bp.route("/export/era-csv")
def export_era_csv():
    """Export ERA claim lines to CSV."""
    from flask import current_app, send_file
    from app.export.csv_exporter import export_era_csv
    result = export_era_csv(app=current_app)
    return send_file(result["filepath"], as_attachment=True,
                     download_name="era_claims.csv", mimetype="text/csv")


@api_bp.route("/export/trigger", methods=["POST"])
def export_trigger():
    """Trigger a CSV export (returns metadata, not the file)."""
    from flask import current_app
    from app.export.csv_exporter import export_billing_csv
    result = export_billing_csv(app=current_app)
    return jsonify(result)


# ══════════════════════════════════════════════════════════════════
#  F-20: Backup
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/backup/run", methods=["POST"])
def backup_run():
    """Run a database backup."""
    from flask import current_app
    from app.infra.backup_manager import run_backup
    return jsonify(run_backup(app=current_app))


@api_bp.route("/backup/status")
def backup_status():
    """Get backup status and history."""
    from flask import current_app
    from app.infra.backup_manager import get_backup_history
    backup_dir = current_app.config.get("BACKUP_FOLDER", "backup")
    return jsonify(get_backup_history(backup_dir))


@api_bp.route("/backup/history")
def backup_history():
    """Get backup history."""
    from flask import current_app
    from app.infra.backup_manager import get_backup_history
    backup_dir = current_app.config.get("BACKUP_FOLDER", "backup")
    return jsonify(get_backup_history(backup_dir))


# ══════════════════════════════════════════════════════════════════
#  Admin: Payers & Fee Schedule
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/admin/payers")
def admin_payers():
    """List all payer configurations."""
    payers = Payer.query.order_by(Payer.code).all()
    return jsonify([{
        "code": p.code,
        "display_name": p.display_name,
        "filing_deadline_days": p.filing_deadline_days,
        "expected_has_secondary": p.expected_has_secondary,
        "alert_threshold_pct": p.alert_threshold_pct,
    } for p in payers])


@api_bp.route("/admin/payers", methods=["POST"])
def admin_payer_upsert():
    """Create or update a payer."""
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400
    code = request.json.get("code")
    if not code:
        return jsonify({"error": "code required"}), 400
    payer = Payer.query.get(code)
    if not payer:
        payer = Payer(code=code)
        db.session.add(payer)
    payer.display_name = request.json.get("display_name", payer.display_name)
    payer.filing_deadline_days = request.json.get("filing_deadline_days", payer.filing_deadline_days or 180)
    payer.expected_has_secondary = request.json.get("expected_has_secondary", payer.expected_has_secondary)
    payer.alert_threshold_pct = request.json.get("alert_threshold_pct", payer.alert_threshold_pct)
    db.session.commit()
    return jsonify({"status": "saved", "code": code})


@api_bp.route("/admin/fee-schedule")
def admin_fee_schedule():
    """List fee schedule entries."""
    entries = FeeSchedule.query.order_by(FeeSchedule.payer_code, FeeSchedule.modality).all()
    return jsonify([{
        "id": fs.id,
        "payer_code": fs.payer_code,
        "modality": fs.modality,
        "expected_rate": fs.expected_rate,
        "underpayment_threshold": fs.underpayment_threshold,
    } for fs in entries])


@api_bp.route("/admin/fee-schedule", methods=["POST"])
def admin_fee_schedule_upsert():
    """Create or update a fee schedule entry."""
    if not request.is_json:
        return jsonify({"error": "JSON body required"}), 400
    payer_code = request.json.get("payer_code")
    modality = request.json.get("modality")
    rate = request.json.get("expected_rate")
    if not all([payer_code, modality, rate]):
        return jsonify({"error": "payer_code, modality, expected_rate required"}), 400

    entry = FeeSchedule.query.filter_by(payer_code=payer_code, modality=modality).first()
    if not entry:
        entry = FeeSchedule(payer_code=payer_code, modality=modality, expected_rate=rate)
        db.session.add(entry)
    else:
        entry.expected_rate = rate
    entry.underpayment_threshold = request.json.get("underpayment_threshold", entry.underpayment_threshold or 0.80)
    db.session.commit()
    return jsonify({"status": "saved", "id": entry.id})


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


# ══════════════════════════════════════════════════════════════════
#  Smart Matching API Endpoints (SM-01 through SM-12)
# ══════════════════════════════════════════════════════════════════

# ── Match Outcomes (SM-01a) ──────────────────────────────────────

@api_bp.route("/smart/outcomes")
def smart_outcomes():
    """View match outcome history."""
    from app.matching.match_memory import get_outcomes, get_outcome_stats
    carrier = request.args.get("carrier")
    limit = min(int(request.args.get("limit", 100)), 500)
    outcomes = get_outcomes(carrier=carrier, limit=limit)
    stats = get_outcome_stats()
    return jsonify({
        "outcomes": [{
            "id": o.id,
            "era_claim_id": o.era_claim_id,
            "billing_record_id": o.billing_record_id,
            "action": o.action,
            "original_score": o.original_score,
            "name_score": o.name_score,
            "date_score": o.date_score,
            "modality_score": o.modality_score,
            "carrier": o.carrier,
            "modality": o.modality,
            "created_at": o.created_at.isoformat() if o.created_at else None,
        } for o in outcomes],
        "stats": stats,
    })


# ── Learned Weights (SM-01b, SM-02) ─────────────────────────────

@api_bp.route("/smart/weights")
def smart_weights():
    """View all learned weights."""
    from app.matching.weight_optimizer import get_all_learned_weights, get_learned_weights
    carrier = request.args.get("carrier")
    modality = request.args.get("modality")
    if carrier or modality:
        return jsonify(get_learned_weights(carrier=carrier, modality=modality))
    return jsonify({"weights": get_all_learned_weights()})


@api_bp.route("/smart/weights/reset", methods=["POST"])
def smart_weights_reset():
    """Reset learned weights to defaults."""
    from app.matching.weight_optimizer import reset_learned_weights
    data = request.get_json(silent=True) or {}
    count = reset_learned_weights(
        carrier=data.get("carrier"),
        modality=data.get("modality"),
    )
    return jsonify({"reset": count})


@api_bp.route("/smart/weights/optimize", methods=["POST"])
def smart_weights_optimize():
    """Trigger weight optimization."""
    from app.matching.weight_optimizer import update_learned_weights
    data = request.get_json(silent=True) or {}
    result = update_learned_weights(
        carrier=data.get("carrier"),
        modality=data.get("modality"),
    )
    if result:
        return jsonify({"status": "optimized", "sample_size": result.sample_size})
    return jsonify({"status": "insufficient_data"})


# ── Name Aliases (SM-04) ────────────────────────────────────────

@api_bp.route("/smart/aliases")
def smart_aliases():
    """View all name alias pairs."""
    from app.models import NameAlias
    aliases = NameAlias.query.order_by(NameAlias.match_count.desc()).all()
    return jsonify({"aliases": [{
        "id": a.id,
        "name_a": a.name_a,
        "name_b": a.name_b,
        "match_count": a.match_count,
        "active": a.match_count >= 2,
        "created_at": a.created_at.isoformat() if a.created_at else None,
    } for a in aliases]})


@api_bp.route("/smart/aliases/<int:alias_id>", methods=["DELETE"])
def smart_alias_delete(alias_id):
    """Remove an incorrect name alias."""
    from app.models import NameAlias
    alias = db.session.get(NameAlias, alias_id)
    if not alias:
        return jsonify({"error": "Alias not found"}), 404
    db.session.delete(alias)
    db.session.commit()
    return jsonify({"status": "deleted"})


# ── Recovery Rates (SM-03) ──────────────────────────────────────

@api_bp.route("/smart/recovery-rates")
def smart_recovery_rates():
    """View learned recovery rates per carrier+reason."""
    from app.revenue.denial_memory import get_recovery_rates_list
    return jsonify({"rates": get_recovery_rates_list()})


# ── Payment Patterns (SM-07) ────────────────────────────────────

@api_bp.route("/smart/payment-patterns")
def smart_payment_patterns():
    """View learned payment patterns per carrier/modality."""
    from app.revenue.payment_patterns import get_payment_patterns
    days = int(request.args.get("days", 90))
    return jsonify({"patterns": get_payment_patterns(days=days)})


@api_bp.route("/smart/fee-suggestions")
def smart_fee_suggestions():
    """View suggested fee schedule updates."""
    from app.revenue.payment_patterns import suggest_fee_updates
    return jsonify({"suggestions": suggest_fee_updates()})


@api_bp.route("/smart/fee-update", methods=["POST"])
def smart_fee_update():
    """Apply a fee schedule update."""
    from app.revenue.payment_patterns import apply_fee_update
    data = request.get_json()
    if not data or not data.get("carrier") or not data.get("modality") or not data.get("rate"):
        return jsonify({"error": "carrier, modality, and rate required"}), 400
    result = apply_fee_update(data["carrier"], data["modality"], float(data["rate"]))
    return jsonify(result)


# ── Denial Patterns (SM-12) ─────────────────────────────────────

@api_bp.route("/smart/denial-patterns")
def smart_denial_patterns():
    """View detected recurring denial patterns."""
    from app.revenue.denial_memory import detect_denial_patterns
    return jsonify({"patterns": detect_denial_patterns()})


# ── CPT Map (SM-05) ─────────────────────────────────────────────

@api_bp.route("/smart/cpt-map")
def smart_cpt_map():
    """View CPT->modality mappings (hardcoded + learned)."""
    from app.matching.match_memory import get_cpt_modality_map
    from app.models import LearnedCptModality
    all_entries = LearnedCptModality.query.order_by(LearnedCptModality.match_count.desc()).all()
    return jsonify({"mappings": [{
        "cpt_prefix": e.cpt_prefix,
        "modality": e.modality,
        "confidence": e.confidence,
        "source": e.source,
        "match_count": e.match_count,
    } for e in all_entries]})


# ── Normalization (SM-09) ───────────────────────────────────────

@api_bp.route("/smart/normalization/pending")
def smart_normalization_pending():
    """View unmapped values needing approval."""
    from app.import_engine.normalization_learner import get_pending_normalizations
    pending = get_pending_normalizations()
    return jsonify({"pending": [{
        "id": n.id,
        "category": n.category,
        "raw_value": n.raw_value,
        "normalized_value": n.normalized_value,
        "use_count": n.use_count,
    } for n in pending]})


@api_bp.route("/smart/normalization/approve", methods=["POST"])
def smart_normalization_approve():
    """Approve a normalization suggestion."""
    from app.import_engine.normalization_learner import approve_normalization
    data = request.get_json()
    if not data or not data.get("id"):
        return jsonify({"error": "id required"}), 400
    result = approve_normalization(
        int(data["id"]),
        normalized_value=data.get("normalized_value"),
    )
    if result:
        return jsonify({"status": "approved", "id": result.id})
    return jsonify({"error": "Not found"}), 404


@api_bp.route("/smart/normalization/reject", methods=["POST"])
def smart_normalization_reject():
    """Reject a normalization suggestion."""
    from app.import_engine.normalization_learner import reject_normalization
    data = request.get_json()
    if not data or not data.get("id"):
        return jsonify({"error": "id required"}), 400
    reject_normalization(int(data["id"]))
    return jsonify({"status": "rejected"})


# ── Column Learning (SM-08) ─────────────────────────────────────

@api_bp.route("/smart/column-mappings")
def smart_column_mappings():
    """View all learned column mappings."""
    from app.models import ColumnAliasLearned
    mappings = ColumnAliasLearned.query.order_by(ColumnAliasLearned.use_count.desc()).all()
    return jsonify({"mappings": [{
        "id": m.id,
        "source_name": m.source_name,
        "target_field": m.target_field,
        "source_format": m.source_format,
        "confidence": m.confidence,
        "use_count": m.use_count,
    } for m in mappings]})


@api_bp.route("/smart/column-mappings", methods=["POST"])
def smart_column_mapping_add():
    """Add a learned column mapping."""
    from app.import_engine.column_learner import learn_column_mapping
    data = request.get_json()
    if not data or not data.get("source_name") or not data.get("target_field"):
        return jsonify({"error": "source_name and target_field required"}), 400
    learn_column_mapping(
        data["source_name"],
        data["target_field"],
        source_format=data.get("source_format"),
    )
    return jsonify({"status": "learned"})


# ── Calibration (SM-10) ─────────────────────────────────────────

@api_bp.route("/smart/calibration")
def smart_calibration():
    """View confidence calibration stats."""
    from app.matching.calibration import get_calibration_stats
    return jsonify(get_calibration_stats())


# ── Smart Analytics Dashboard (SM-UI1) ──────────────────────────

@api_bp.route("/smart/analytics")
def smart_analytics():
    """Comprehensive smart matching analytics."""
    from app.matching.match_memory import get_outcome_stats
    from app.matching.weight_optimizer import get_all_learned_weights
    from app.matching.calibration import train_calibration, get_calibration_stats
    from app.revenue.denial_memory import get_recovery_rates_list, detect_denial_patterns
    from app.revenue.payment_patterns import get_payment_patterns, suggest_fee_updates
    from app.models import NameAlias, MatchOutcome

    outcome_stats = get_outcome_stats()
    all_weights = get_all_learned_weights()
    alias_count = NameAlias.query.count()
    active_aliases = NameAlias.query.filter(NameAlias.match_count >= 2).count()
    calibration = get_calibration_stats()
    recovery_rates = get_recovery_rates_list()
    denial_patterns = detect_denial_patterns()
    payment_patterns = get_payment_patterns()
    fee_suggestions = suggest_fee_updates()

    # Accuracy trend (last 10 batches of 25)
    accuracy_trend = []
    total_outcomes = MatchOutcome.query.count()
    if total_outcomes > 0:
        all_outcomes = MatchOutcome.query.filter(
            MatchOutcome.action.in_(["CONFIRMED", "REJECTED"]),
            MatchOutcome.original_score.isnot(None),
        ).order_by(MatchOutcome.created_at).all()

        batch_size = max(25, len(all_outcomes) // 10)
        for i in range(0, len(all_outcomes), batch_size):
            batch = all_outcomes[i:i + batch_size]
            if not batch:
                break
            correct = sum(1 for o in batch if (o.action == "CONFIRMED" and o.original_score >= 0.80) or
                          (o.action == "REJECTED" and o.original_score < 0.80))
            accuracy_trend.append({
                "batch": i // batch_size + 1,
                "sample_size": len(batch),
                "accuracy": round(correct / len(batch), 4),
            })

    return jsonify({
        "outcome_stats": outcome_stats,
        "learned_weights": all_weights,
        "aliases": {"total": alias_count, "active": active_aliases},
        "calibration": calibration,
        "recovery_rates": recovery_rates,
        "denial_patterns": denial_patterns[:10],
        "payment_patterns": payment_patterns[:10],
        "fee_suggestions": fee_suggestions[:10],
        "accuracy_trend": accuracy_trend,
    })


@api_bp.route("/smart/dashboard")
def smart_dashboard_data():
    """Summary data for the smart matching dashboard."""
    from app.models import MatchOutcome, NameAlias, LearnedWeights, DenialOutcome
    from app.matching.weight_optimizer import get_all_learned_weights

    total_outcomes = MatchOutcome.query.count()
    confirmed = MatchOutcome.query.filter_by(action="CONFIRMED").count()
    rejected = MatchOutcome.query.filter_by(action="REJECTED").count()

    all_weights = get_all_learned_weights()
    active_aliases = NameAlias.query.filter(NameAlias.match_count >= 2).count()
    total_denial_outcomes = DenialOutcome.query.count()

    return jsonify({
        "match_outcomes": {
            "total": total_outcomes,
            "confirmed": confirmed,
            "rejected": rejected,
            "confirm_rate": round(confirmed / total_outcomes, 4) if total_outcomes > 0 else 0,
        },
        "learned_weights_count": len(all_weights),
        "active_aliases": active_aliases,
        "denial_outcomes": total_denial_outcomes,
        "features_active": {
            "adaptive_weights": any(w["sample_size"] >= 50 for w in all_weights),
            "name_aliases": active_aliases > 0,
            "denial_learning": total_denial_outcomes >= 10,
        },
    })


# ══════════════════════════════════════════════════════════════════
#  Smart Insights Engine (Carrier Scoring, Anomalies, Risk, Forecast)
# ══════════════════════════════════════════════════════════════════

@api_bp.route("/smart/carrier-scores")
def smart_carrier_scores():
    """Carrier behavior scorecards (payment reliability, consistency, grade)."""
    from app.analytics.smart_insights import score_carriers
    days = request.args.get("days", 180, type=int)
    return jsonify({"carriers": score_carriers(days=days)})


@api_bp.route("/smart/anomalies")
def smart_anomalies():
    """Detect anomalous billing patterns in recent data."""
    from app.analytics.smart_insights import detect_anomalies
    days = request.args.get("days", 30, type=int)
    return jsonify({"anomalies": detect_anomalies(days=days)})


@api_bp.route("/smart/denial-risk")
def smart_denial_risk():
    """Predictive denial risk score for a carrier/modality combination."""
    from app.analytics.smart_insights import score_denial_risk
    carrier = request.args.get("carrier")
    modality = request.args.get("modality")
    return jsonify(score_denial_risk(carrier=carrier, modality=modality))


@api_bp.route("/smart/denial-risk/<int:billing_id>")
def smart_denial_risk_record(billing_id):
    """Predictive denial risk score for a specific billing record."""
    from app.analytics.smart_insights import score_denial_risk
    record = BillingRecord.query.get_or_404(billing_id)
    return jsonify(score_denial_risk(billing_record=record))


@api_bp.route("/smart/forecast")
def smart_forecast():
    """Revenue forecast for next N months."""
    from app.analytics.smart_insights import forecast_revenue
    months = request.args.get("months", 3, type=int)
    return jsonify(forecast_revenue(months_ahead=months))


@api_bp.route("/smart/insights")
def smart_insights():
    """Top actionable dashboard insights."""
    from app.analytics.smart_insights import generate_insights
    return jsonify({"insights": generate_insights()})


@api_bp.route("/smart/auto-fee-learn", methods=["POST"])
def smart_auto_fee_learn():
    """Auto-learn fee schedule from payment data and apply suggestions."""
    from app.revenue.payment_patterns import suggest_fee_updates, apply_fee_update
    min_count = request.json.get("min_count", 10) if request.is_json else 10
    auto_apply = request.json.get("auto_apply", False) if request.is_json else False
    suggestions = suggest_fee_updates(min_count=min_count)

    applied = []
    if auto_apply:
        for s in suggestions:
            if s["direction"] == "NEW":
                result = apply_fee_update(s["carrier"], s["modality"], s["suggested_rate"])
                applied.append(result)

    return jsonify({
        "suggestions": suggestions,
        "auto_applied": applied,
        "total_suggestions": len(suggestions),
        "total_applied": len(applied),
    })
