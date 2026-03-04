"""Underpayment detection API routes (F-05)."""

from flask import request, jsonify

from app.revenue import bp
from app.extensions import db
from app.models import BillingRecord
from app.utils import parse_pagination, paginate_query

from ocdr.config import UNDERPAYMENT_THRESHOLD


def _underpayment_filters(threshold):
    """Return the standard filter conditions for underpaid records."""
    return [
        BillingRecord.total_payment > 0,
        BillingRecord.expected_rate.isnot(None),
        BillingRecord.expected_rate > 0,
        BillingRecord.pct_of_expected < threshold,
    ]


@bp.route('/underpayments', methods=['GET'])
def list_underpayments():
    """Paginated list of underpaid billing records."""
    page, per_page = parse_pagination()
    threshold = request.args.get('threshold', float(UNDERPAYMENT_THRESHOLD), type=float)

    query = BillingRecord.query.filter(*_underpayment_filters(threshold))

    carrier = request.args.get('carrier')
    if carrier:
        query = query.filter(BillingRecord.insurance_carrier == carrier)

    modality = request.args.get('modality')
    if modality:
        query = query.filter(BillingRecord.modality == modality)

    date_from = request.args.get('date_from')
    if date_from:
        query = query.filter(BillingRecord.service_date >= date_from)

    date_to = request.args.get('date_to')
    if date_to:
        query = query.filter(BillingRecord.service_date <= date_to)

    query = query.order_by(BillingRecord.variance.asc())
    result = paginate_query(query, page, per_page)
    result['threshold'] = threshold
    return jsonify(result)


@bp.route('/underpayments/summary', methods=['GET'])
def underpayment_summary():
    """Aggregate underpayment statistics."""
    threshold = request.args.get('threshold', float(UNDERPAYMENT_THRESHOLD), type=float)
    filters = _underpayment_filters(threshold)

    total_flagged = BillingRecord.query.filter(*filters).count()

    total_variance = (
        db.session.query(db.func.sum(BillingRecord.variance))
        .filter(*filters)
        .scalar()
    ) or 0

    by_carrier = (
        db.session.query(
            BillingRecord.insurance_carrier,
            db.func.count(),
            db.func.sum(BillingRecord.variance),
        )
        .filter(*filters)
        .group_by(BillingRecord.insurance_carrier)
        .all()
    )

    by_modality = (
        db.session.query(
            BillingRecord.modality,
            db.func.count(),
            db.func.sum(BillingRecord.variance),
        )
        .filter(*filters)
        .group_by(BillingRecord.modality)
        .all()
    )

    return jsonify({
        'total_flagged': total_flagged,
        'total_variance': float(total_variance),
        'threshold': threshold,
        'by_carrier': [
            {'carrier': c, 'count': n, 'variance': float(v or 0)}
            for c, n, v in by_carrier
        ],
        'by_modality': [
            {'modality': m, 'count': n, 'variance': float(v or 0)}
            for m, n, v in by_modality
        ],
    })
