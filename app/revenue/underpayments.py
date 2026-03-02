"""Underpayment detection API routes (F-05)."""

from decimal import Decimal

from flask import request, jsonify

from app.revenue import bp
from app.extensions import db
from app.models import BillingRecord

from ocdr.config import UNDERPAYMENT_THRESHOLD


@bp.route('/underpayments', methods=['GET'])
def list_underpayments():
    """Paginated list of underpaid billing records."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)
    threshold = request.args.get('threshold', float(UNDERPAYMENT_THRESHOLD), type=float)

    query = BillingRecord.query.filter(
        BillingRecord.total_payment > 0,
        BillingRecord.expected_rate.isnot(None),
        BillingRecord.expected_rate > 0,
        BillingRecord.pct_of_expected < threshold,
    )

    carrier = request.args.get('carrier')
    if carrier:
        query = query.filter(BillingRecord.insurance_carrier == carrier)

    modality = request.args.get('modality')
    if modality:
        query = query.filter(BillingRecord.modality == modality)

    query = query.order_by(BillingRecord.variance.asc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'items': [r.to_dict() for r in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
        'threshold': threshold,
    })


@bp.route('/underpayments/summary', methods=['GET'])
def underpayment_summary():
    """Aggregate underpayment statistics."""
    threshold = request.args.get('threshold', float(UNDERPAYMENT_THRESHOLD), type=float)

    base = BillingRecord.query.filter(
        BillingRecord.total_payment > 0,
        BillingRecord.expected_rate.isnot(None),
        BillingRecord.expected_rate > 0,
        BillingRecord.pct_of_expected < threshold,
    )

    total_flagged = base.count()
    total_variance = db.session.query(
        db.func.sum(BillingRecord.variance)
    ).filter(
        BillingRecord.total_payment > 0,
        BillingRecord.expected_rate.isnot(None),
        BillingRecord.expected_rate > 0,
        BillingRecord.pct_of_expected < threshold,
    ).scalar() or 0

    by_carrier = (
        db.session.query(
            BillingRecord.insurance_carrier,
            db.func.count(),
            db.func.sum(BillingRecord.variance),
        )
        .filter(
            BillingRecord.total_payment > 0,
            BillingRecord.expected_rate.isnot(None),
            BillingRecord.expected_rate > 0,
            BillingRecord.pct_of_expected < threshold,
        )
        .group_by(BillingRecord.insurance_carrier)
        .all()
    )

    by_modality = (
        db.session.query(
            BillingRecord.modality,
            db.func.count(),
            db.func.sum(BillingRecord.variance),
        )
        .filter(
            BillingRecord.total_payment > 0,
            BillingRecord.expected_rate.isnot(None),
            BillingRecord.expected_rate > 0,
            BillingRecord.pct_of_expected < threshold,
        )
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
