"""F-05: Underpayment Detector

Compares total_payment against fee_schedule.expected_rate for each paid claim.
Flags claims where payment < underpayment_threshold (default 80%) of expected rate.
Implements BR-03 (Gado Premium) and BR-11 (Underpayment Detection).
"""
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from app.models import db, BillingRecord, FeeSchedule

underpayment_bp = Blueprint('underpayment', __name__)


def get_expected_rate(modality, carrier, gado_used=False, is_psma=False):
    """Look up expected rate from fee schedule with BR-02 and BR-03 adjustments."""
    # Check carrier-specific rate first
    rate_entry = FeeSchedule.query.filter_by(
        payer_code=carrier, modality=modality
    ).first()

    if not rate_entry:
        # BR-02: PSMA gets special rate
        if is_psma and modality == 'PET':
            rate_entry = FeeSchedule.query.filter_by(
                payer_code='DEFAULT_PSMA', modality='PET'
            ).first()

        if not rate_entry:
            # Fall back to DEFAULT
            rate_entry = FeeSchedule.query.filter_by(
                payer_code='DEFAULT', modality=modality
            ).first()

    if not rate_entry:
        return None, None

    expected = rate_entry.expected_rate
    threshold = rate_entry.underpayment_threshold

    # BR-03: Gado premium for HMRI and OPEN
    if gado_used and modality in ('HMRI', 'OPEN'):
        expected += 200.0

    return expected, threshold


@underpayment_bp.route('/underpayments', methods=['GET'])
def list_underpayments():
    """GET /api/underpayments - List underpaid claims"""
    carrier_filter = request.args.get('carrier')
    modality_filter = request.args.get('modality')
    custom_threshold = request.args.get('threshold', type=float)
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)

    # Only look at paid claims (total_payment > 0)
    query = BillingRecord.query.filter(BillingRecord.total_payment > 0)

    if carrier_filter:
        query = query.filter(BillingRecord.insurance_carrier == carrier_filter)
    if modality_filter:
        query = query.filter(BillingRecord.modality == modality_filter)

    query = query.order_by(BillingRecord.total_payment.asc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    results = []
    for record in pagination.items:
        expected, threshold = get_expected_rate(
            record.modality, record.insurance_carrier,
            record.gado_used, record.is_psma
        )
        if expected is None:
            continue

        if custom_threshold is not None:
            threshold = custom_threshold

        if record.total_payment < (expected * threshold):
            variance = record.total_payment - expected
            results.append({
                **record.to_dict(),
                'expected_rate': expected,
                'variance': round(variance, 2),
                'pct_of_expected': round(record.total_payment / expected, 4) if expected else 0,
            })

    return jsonify({
        'underpayments': results,
        'total': len(results),
        'page': page,
    })


@underpayment_bp.route('/underpayments/summary', methods=['GET'])
def underpayment_summary():
    """GET /api/underpayments/summary - Aggregate underpayment stats"""
    paid_records = BillingRecord.query.filter(BillingRecord.total_payment > 0).all()

    total_flagged = 0
    total_variance = 0.0
    by_carrier = {}
    by_modality = {}

    for record in paid_records:
        expected, threshold = get_expected_rate(
            record.modality, record.insurance_carrier,
            record.gado_used, record.is_psma
        )
        if expected is None:
            continue

        if record.total_payment < (expected * threshold):
            total_flagged += 1
            variance = record.total_payment - expected
            total_variance += variance

            # By carrier
            c = record.insurance_carrier
            if c not in by_carrier:
                by_carrier[c] = {'count': 0, 'variance': 0.0}
            by_carrier[c]['count'] += 1
            by_carrier[c]['variance'] += variance

            # By modality
            m = record.modality
            if m not in by_modality:
                by_modality[m] = {'count': 0, 'variance': 0.0}
            by_modality[m]['count'] += 1
            by_modality[m]['variance'] += variance

    # Round variances
    for v in by_carrier.values():
        v['variance'] = round(v['variance'], 2)
    for v in by_modality.values():
        v['variance'] = round(v['variance'], 2)

    return jsonify({
        'total_flagged': total_flagged,
        'total_variance': round(total_variance, 2),
        'by_carrier': [{'carrier': k, **v} for k, v in sorted(by_carrier.items(), key=lambda x: x[1]['variance'])],
        'by_modality': [{'modality': k, **v} for k, v in sorted(by_modality.items(), key=lambda x: x[1]['variance'])],
    })
