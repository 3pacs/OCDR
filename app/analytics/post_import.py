"""Post-import auto-analysis endpoint.

After data is imported, this endpoint analyzes the current state and
provides KPIs, breakdowns, and recommended next steps.
"""
from datetime import date
from flask import Blueprint, jsonify
from sqlalchemy import func

from app.models import db, BillingRecord, EraPayment, EraClaimLine
from app.revenue.underpayment_detector import get_expected_rate
from app.revenue.filing_deadlines import categorize_deadline

analysis_bp = Blueprint('analysis', __name__)


@analysis_bp.route('/analysis/post-import', methods=['GET'])
def post_import_analysis():
    """GET /api/analysis/post-import — Full analysis of imported data.

    Returns KPIs, carrier breakdown, and recommended next steps.
    """
    total_records = BillingRecord.query.count()
    if total_records == 0:
        return jsonify({
            'total_records': 0,
            'message': 'No data imported yet.',
            'recommendations': [
                'Import your Excel file: POST /api/import/excel or use the Import page',
                'Import 835 ERA files: POST /api/import/835',
                'Or use CLI: python manage.py import-excel /path/to/OCMRI.xlsx',
            ],
        })

    today = date.today()

    # Core metrics
    total_revenue = db.session.query(func.sum(BillingRecord.total_payment)).scalar() or 0
    unpaid_claims = BillingRecord.query.filter(BillingRecord.total_payment == 0).count()
    era_payments = EraPayment.query.count()
    era_claims = EraClaimLine.query.count()

    # Underpayment analysis (sampled for performance on large datasets)
    underpaid_claims = 0
    underpaid_variance = 0.0
    paid_records = BillingRecord.query.filter(BillingRecord.total_payment > 0).all()
    for r in paid_records:
        expected, threshold = get_expected_rate(
            r.modality, r.insurance_carrier, r.gado_used, r.is_psma
        )
        if expected and float(r.total_payment) < (float(expected) * float(threshold)):
            underpaid_claims += 1
            underpaid_variance += float(r.total_payment) - float(expected)

    # Filing deadline alerts
    alerts_query = BillingRecord.query.filter(
        BillingRecord.total_payment == 0,
        BillingRecord.appeal_deadline.isnot(None),
    ).all()
    past_deadline = sum(1 for a in alerts_query if categorize_deadline(a.appeal_deadline, today) == 'PAST_DEADLINE')
    warning_30day = sum(1 for a in alerts_query if categorize_deadline(a.appeal_deadline, today) == 'WARNING_30DAY')
    filing_alerts = past_deadline + warning_30day

    # Secondary follow-up (M/M with primary but no secondary)
    # Note: CALOPTIMA/Medi-Cal patients generally don't have secondary
    secondary_missing = BillingRecord.query.filter(
        BillingRecord.primary_payment > 0,
        BillingRecord.secondary_payment == 0,
        BillingRecord.insurance_carrier.in_(['M/M']),
    ).count()

    # PSMA PET count
    psma_count = BillingRecord.query.filter(BillingRecord.is_psma == True).count()  # noqa: E712

    # Carrier breakdown
    carrier_stats = db.session.query(
        BillingRecord.insurance_carrier,
        func.count(BillingRecord.id),
        func.sum(BillingRecord.total_payment),
    ).group_by(BillingRecord.insurance_carrier).order_by(
        func.sum(BillingRecord.total_payment).desc()
    ).all()

    by_carrier = []
    for carrier, count, revenue in carrier_stats:
        rev = float(revenue or 0)
        by_carrier.append({
            'carrier': carrier,
            'count': count,
            'revenue': round(rev, 2),
            'avg_payment': round(rev / count, 2) if count > 0 else 0,
        })

    # Modality breakdown
    modality_stats = db.session.query(
        BillingRecord.modality,
        func.count(BillingRecord.id),
        func.sum(BillingRecord.total_payment),
    ).group_by(BillingRecord.modality).order_by(
        func.sum(BillingRecord.total_payment).desc()
    ).all()

    by_modality = []
    for modality, count, revenue in modality_stats:
        rev = float(revenue or 0)
        by_modality.append({
            'modality': modality,
            'count': count,
            'revenue': round(rev, 2),
            'avg_payment': round(rev / count, 2) if count > 0 else 0,
        })

    # Year-over-year
    yearly_stats = db.session.query(
        func.strftime('%Y', BillingRecord.service_date),
        func.count(BillingRecord.id),
        func.sum(BillingRecord.total_payment),
    ).group_by(func.strftime('%Y', BillingRecord.service_date)).order_by(
        func.strftime('%Y', BillingRecord.service_date)
    ).all()

    by_year = []
    for year, count, revenue in yearly_stats:
        by_year.append({
            'year': year,
            'count': count,
            'revenue': round(float(revenue or 0), 2),
        })

    # Generate recommendations
    recommendations = []
    if past_deadline > 0:
        recommendations.append(
            f'URGENT: {past_deadline} claims are PAST filing deadline — '
            f'revenue is unrecoverable without immediate action. '
            f'Visit /api/filing-deadlines/alerts'
        )
    if warning_30day > 0:
        recommendations.append(
            f'{warning_30day} claims approaching filing deadline within 30 days — '
            f'prioritize these for follow-up'
        )
    if underpaid_claims > 0:
        recommendations.append(
            f'{underpaid_claims:,} claims are underpaid (${abs(underpaid_variance):,.2f} total gap) — '
            f'review carrier contracts and appeal where possible. '
            f'Visit /api/underpayments/summary'
        )
    if secondary_missing > 0:
        recommendations.append(
            f'{secondary_missing:,} claims have primary payment but missing secondary '
            f'(M/M) — estimated recoverable revenue. '
            f'Visit /api/secondary-followup'
        )
    if era_payments == 0:
        recommendations.append(
            'Import 835 ERA files to enable payment matching and denial tracking. '
            'Use the Import page or: python manage.py import-835 /path/to/file.835'
        )
    if era_claims > 0:
        unmatched = EraClaimLine.query.filter(EraClaimLine.matched_billing_id.is_(None)).count()
        if unmatched > 0:
            recommendations.append(
                f'{unmatched} ERA claim lines are unmatched — '
                f'run auto-matching: POST /api/match/run'
            )
    if unpaid_claims > 0:
        recommendations.append(
            f'{unpaid_claims:,} claims show $0 payment — '
            f'review denial queue at /api/denials/queue'
        )
    if psma_count > 0:
        recommendations.append(
            f'{psma_count} PSMA PET scans detected — ensure they are billed at '
            f'$8,046 rate (not standard $2,500)'
        )

    return jsonify({
        'total_records': total_records,
        'total_revenue': round(float(total_revenue), 2),
        'unpaid_claims': unpaid_claims,
        'underpaid_claims': underpaid_claims,
        'underpaid_variance': round(underpaid_variance, 2),
        'filing_alerts': filing_alerts,
        'past_deadline': past_deadline,
        'warning_30day': warning_30day,
        'secondary_missing': secondary_missing,
        'psma_count': psma_count,
        'era_payments': era_payments,
        'era_claims': era_claims,
        'by_carrier': by_carrier,
        'by_modality': by_modality,
        'by_year': by_year,
        'recommendations': recommendations,
    })
