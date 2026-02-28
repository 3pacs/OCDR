"""F-06: Timely Filing Deadline Tracker

Computes appeal_deadline = service_date + payers.filing_deadline_days.
Flags claims where total_payment=0 and approaching/past deadline.
Implements BR-05 (Timely Filing Alert).
"""
from datetime import date, timedelta
from flask import Blueprint, request, jsonify
from app.models import db, BillingRecord, Payer

filing_bp = Blueprint('filing', __name__)


def categorize_deadline(appeal_deadline, today=None):
    """Categorize a claim's filing deadline status.

    Returns: PAST_DEADLINE, WARNING_30DAY, or SAFE
    """
    if today is None:
        today = date.today()
    if appeal_deadline is None:
        return 'UNKNOWN'
    if today > appeal_deadline:
        return 'PAST_DEADLINE'
    if today > (appeal_deadline - timedelta(days=30)):
        return 'WARNING_30DAY'
    return 'SAFE'


@filing_bp.route('/filing-deadlines', methods=['GET'])
def list_filing_deadlines():
    """GET /api/filing-deadlines - Filing deadline status for unpaid claims"""
    status_filter = request.args.get('status')  # PAST, WARNING, SAFE
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Only unpaid claims matter for filing deadlines
    query = BillingRecord.query.filter(BillingRecord.total_payment == 0)
    query = query.filter(BillingRecord.appeal_deadline.isnot(None))
    query = query.order_by(BillingRecord.appeal_deadline.asc())

    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    today = date.today()

    results = []
    for record in pagination.items:
        status = categorize_deadline(record.appeal_deadline, today)

        if status_filter:
            if status_filter == 'PAST' and status != 'PAST_DEADLINE':
                continue
            if status_filter == 'WARNING' and status != 'WARNING_30DAY':
                continue
            if status_filter == 'SAFE' and status != 'SAFE':
                continue

        days_remaining = (record.appeal_deadline - today).days if record.appeal_deadline else None

        results.append({
            **record.to_dict(),
            'deadline_status': status,
            'days_remaining': days_remaining,
        })

    return jsonify({
        'claims': results,
        'total': len(results),
        'page': page,
    })


@filing_bp.route('/filing-deadlines/alerts', methods=['GET'])
def filing_alerts():
    """GET /api/filing-deadlines/alerts - Active alerts only (past deadline + warning)"""
    today = date.today()
    warning_date = today + timedelta(days=30)

    # Unpaid claims where deadline is within 30 days or past
    query = BillingRecord.query.filter(
        BillingRecord.total_payment == 0,
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline <= warning_date,
    ).order_by(BillingRecord.appeal_deadline.asc())

    claims = query.all()

    past_deadline = []
    warning = []

    for claim in claims:
        status = categorize_deadline(claim.appeal_deadline, today)
        days_remaining = (claim.appeal_deadline - today).days

        entry = {
            **claim.to_dict(),
            'deadline_status': status,
            'days_remaining': days_remaining,
        }

        if status == 'PAST_DEADLINE':
            past_deadline.append(entry)
        elif status == 'WARNING_30DAY':
            warning.append(entry)

    return jsonify({
        'past_deadline': len(past_deadline),
        'warning': len(warning),
        'details': past_deadline + warning,
    })
