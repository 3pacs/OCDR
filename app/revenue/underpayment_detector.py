"""F-05: Underpayment Detector.

Compares total_payment vs fee_schedule.expected_rate, flags underpaid claims.
Fully sortable and filterable.
"""

import math
from flask import Blueprint, jsonify, request, render_template

from app import get_db

underpayment_bp = Blueprint('underpayments', __name__)

SORTABLE_COLUMNS = {
    'patient_name':      'b.patient_name',
    'insurance_carrier': 'b.insurance_carrier',
    'modality':          'b.modality',
    'scan_type':         'b.scan_type',
    'service_date':      'b.service_date',
    'total_payment':     'b.total_payment',
    'expected_rate':     'f.expected_rate',
    'variance':          'variance',
    'variance_pct':      'variance_pct',
    'referring_doctor':  'b.referring_doctor',
    'billed_amount':     'b.billed_amount',
}


def _build_underpayment_query(*, count_only=False, filters=None,
                               sort_by='variance', sort_order='asc',
                               limit=None, offset=0):
    select_cols = "COUNT(*)" if count_only else """
        b.id,
        b.patient_name,
        b.referring_doctor,
        b.scan_type,
        b.insurance_carrier,
        b.modality,
        b.service_date,
        b.total_payment,
        b.billed_amount,
        b.gado_used,
        f.expected_rate,
        ROUND(b.total_payment - f.expected_rate, 2) AS variance,
        ROUND(b.total_payment / f.expected_rate, 4) AS variance_pct
    """

    sql = f"""SELECT {select_cols}
        FROM billing_records b
        JOIN fee_schedule f ON b.modality = f.modality
            AND (f.payer_code = b.insurance_carrier OR f.payer_code = 'DEFAULT')
        WHERE b.total_payment > 0
          AND b.total_payment < (f.expected_rate * f.underpayment_threshold)
    """
    params = []

    if filters:
        if filters.get('carrier'):
            sql += " AND b.insurance_carrier = ?"
            params.append(filters['carrier'])
        if filters.get('modality'):
            sql += " AND b.modality = ?"
            params.append(filters['modality'])
        if filters.get('date_from'):
            sql += " AND b.service_date >= ?"
            params.append(filters['date_from'])
        if filters.get('date_to'):
            sql += " AND b.service_date <= ?"
            params.append(filters['date_to'])
        if filters.get('search'):
            sql += " AND (b.patient_name LIKE ? OR b.referring_doctor LIKE ?)"
            term = f"%{filters['search']}%"
            params.extend([term, term])

    if not count_only:
        sort_col = SORTABLE_COLUMNS.get(sort_by, 'variance')
        direction = 'ASC' if sort_order.upper() == 'ASC' else 'DESC'
        sql += f" ORDER BY {sort_col} {direction}"

        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

    return sql, params


@underpayment_bp.route('/underpayments')
def underpayments_page():
    return render_template('underpayments.html')


@underpayment_bp.route('/api/underpayments')
def api_underpayments():
    filters = {
        'carrier':   request.args.get('carrier'),
        'modality':  request.args.get('modality'),
        'date_from': request.args.get('date_from'),
        'date_to':   request.args.get('date_to'),
        'search':    request.args.get('search'),
    }
    sort_by = request.args.get('sort_by', 'variance')
    sort_order = request.args.get('sort_order', 'asc')
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(200, max(1, int(request.args.get('per_page', 50))))
    offset = (page - 1) * per_page

    db = get_db()

    count_sql, count_params = _build_underpayment_query(count_only=True, filters=filters)
    total = db.execute(count_sql, count_params).fetchone()[0]

    data_sql, data_params = _build_underpayment_query(
        filters=filters, sort_by=sort_by, sort_order=sort_order,
        limit=per_page, offset=offset,
    )
    rows = db.execute(data_sql, data_params).fetchall()

    return jsonify({
        'data': [dict(r) for r in rows],
        'total': total,
        'page': page,
        'per_page': per_page,
        'total_pages': math.ceil(total / per_page) if total else 0,
        'sort_by': sort_by,
        'sort_order': sort_order,
        'sortable_columns': list(SORTABLE_COLUMNS.keys()),
    })


@underpayment_bp.route('/api/underpayments/summary')
def api_underpayments_summary():
    db = get_db()
    summary = db.execute("""
        SELECT
            COUNT(*) as total_flagged,
            ROUND(SUM(b.total_payment - f.expected_rate), 2) as total_variance,
            b.insurance_carrier,
            b.modality
        FROM billing_records b
        JOIN fee_schedule f ON b.modality = f.modality
            AND (f.payer_code = b.insurance_carrier OR f.payer_code = 'DEFAULT')
        WHERE b.total_payment > 0
          AND b.total_payment < (f.expected_rate * f.underpayment_threshold)
        GROUP BY b.insurance_carrier, b.modality
        ORDER BY total_variance ASC
    """).fetchall()

    total_flagged = sum(r['total_flagged'] for r in summary)
    total_variance = sum(r['total_variance'] for r in summary)

    return jsonify({
        'total_flagged': total_flagged,
        'total_variance': round(total_variance, 2),
        'by_carrier_modality': [dict(r) for r in summary],
    })


@underpayment_bp.route('/api/underpayments/filters')
def api_underpayment_filters():
    db = get_db()
    carriers = [r[0] for r in db.execute(
        "SELECT DISTINCT insurance_carrier FROM billing_records WHERE total_payment > 0 ORDER BY insurance_carrier"
    ).fetchall()]
    modalities = [r[0] for r in db.execute(
        "SELECT DISTINCT modality FROM billing_records WHERE total_payment > 0 ORDER BY modality"
    ).fetchall()]
    return jsonify({'carriers': carriers, 'modalities': modalities})
