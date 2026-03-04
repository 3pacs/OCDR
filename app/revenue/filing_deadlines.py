"""Timely filing deadline tracker API routes (F-06)."""

from datetime import date, timedelta

from flask import request, jsonify

from app.revenue import bp
from app.extensions import db
from app.models import BillingRecord
from app.utils import parse_pagination


def _unpaid_base_query():
    """Base query for unpaid records that have a filing deadline."""
    return BillingRecord.query.filter(
        db.or_(
            BillingRecord.total_payment == 0,
            BillingRecord.total_payment.is_(None),
        ),
        BillingRecord.appeal_deadline.isnot(None),
    )


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
    page, per_page = parse_pagination()
    status_filter = request.args.get('status')
    today = date.today()

    query = _unpaid_base_query()

    # Apply carrier filter
    carrier = request.args.get('carrier')
    if carrier:
        query = query.filter(BillingRecord.insurance_carrier == carrier)

    # Apply modality filter
    modality = request.args.get('modality')
    if modality:
        query = query.filter(BillingRecord.modality == modality)

    # Apply status filter in SQL before pagination (not after)
    if status_filter == 'PAST_DEADLINE':
        query = query.filter(BillingRecord.appeal_deadline < today)
    elif status_filter == 'WARNING_30DAY':
        query = query.filter(
            BillingRecord.appeal_deadline >= today,
            BillingRecord.appeal_deadline <= today + timedelta(days=30),
        )
    elif status_filter == 'SAFE':
        query = query.filter(BillingRecord.appeal_deadline > today + timedelta(days=30))

    # Order by deadline ascending (most urgent first)
    query = query.order_by(BillingRecord.appeal_deadline.asc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)
    items = [_classify_record(r) for r in pagination.items]

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

    # Past deadline: appeal_deadline < today
    past_query = _unpaid_base_query().filter(
        BillingRecord.appeal_deadline < today,
    )
    past_count = past_query.count()

    # Warning: appeal_deadline between today and today+30
    warning_query = _unpaid_base_query().filter(
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
