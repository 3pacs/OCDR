"""Timely filing deadline tracker API routes (F-06)."""

from datetime import date, timedelta

from flask import request, jsonify

from app.revenue import bp
from app.extensions import db
from app.models import BillingRecord


def _classify_record(record):
    """Add filing status fields to a record dict based on appeal_deadline."""
    d = record.to_dict()
    today = date.today()
    deadline = record.appeal_deadline

    if deadline is None:
        d['filing_status'] = 'UNKNOWN'
        d['days_remaining'] = None
    elif today > deadline:
        d['filing_status'] = 'PAST_DEADLINE'
        d['days_remaining'] = (deadline - today).days
    elif today > deadline - timedelta(days=30):
        d['filing_status'] = 'WARNING_30DAY'
        d['days_remaining'] = (deadline - today).days
    else:
        d['filing_status'] = 'SAFE'
        d['days_remaining'] = (deadline - today).days

    return d


@bp.route('/filing-deadlines', methods=['GET'])
def list_filing_deadlines():
    """Paginated list of unpaid records with filing deadline status."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    status_filter = request.args.get('status')

    query = BillingRecord.query.filter(
        db.or_(
            BillingRecord.total_payment == 0,
            BillingRecord.total_payment.is_(None),
        ),
        BillingRecord.appeal_deadline.isnot(None),
    )

    # Order by deadline ascending (most urgent first)
    query = query.order_by(BillingRecord.appeal_deadline.asc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    items = [_classify_record(r) for r in pagination.items]

    # Apply status filter after classification
    if status_filter:
        items = [i for i in items if i['filing_status'] == status_filter]

    return jsonify({
        'items': items,
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    })


@bp.route('/filing-deadlines/alerts', methods=['GET'])
def filing_alerts():
    """Return only PAST_DEADLINE and WARNING_30DAY records with counts."""
    today = date.today()
    warn_date = today - timedelta(days=-30)  # 30 days from now

    # Past deadline: appeal_deadline < today
    past_query = BillingRecord.query.filter(
        db.or_(
            BillingRecord.total_payment == 0,
            BillingRecord.total_payment.is_(None),
        ),
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline < today,
    )
    past_count = past_query.count()

    # Warning: appeal_deadline between today and today+30
    warning_query = BillingRecord.query.filter(
        db.or_(
            BillingRecord.total_payment == 0,
            BillingRecord.total_payment.is_(None),
        ),
        BillingRecord.appeal_deadline.isnot(None),
        BillingRecord.appeal_deadline >= today,
        BillingRecord.appeal_deadline <= today + timedelta(days=30),
    )
    warning_count = warning_query.count()

    # Get details for alerts (limit to most urgent)
    past_records = past_query.order_by(BillingRecord.appeal_deadline.asc()).limit(50).all()
    warning_records = warning_query.order_by(BillingRecord.appeal_deadline.asc()).limit(50).all()

    return jsonify({
        'past_deadline': past_count,
        'warning_30day': warning_count,
        'total_alerts': past_count + warning_count,
        'past_deadline_details': [_classify_record(r) for r in past_records],
        'warning_details': [_classify_record(r) for r in warning_records],
    })
