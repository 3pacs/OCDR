"""F-07: Secondary Insurance Follow-Up.

Identifies claims where primary paid but secondary is missing.
Fully sortable and filterable.
"""

import math
from flask import Blueprint, jsonify, request, render_template

from app import get_db

secondary_bp = Blueprint('secondary_followup', __name__)

SORTABLE_COLUMNS = {
    'patient_name':      'b.patient_name',
    'insurance_carrier': 'b.insurance_carrier',
    'modality':          'b.modality',
    'service_date':      'b.service_date',
    'primary_payment':   'b.primary_payment',
    'billed_amount':     'b.billed_amount',
    'referring_doctor':  'b.referring_doctor',
    'scan_type':         'b.scan_type',
    'total_payment':     'b.total_payment',
}


def _build_secondary_query(*, count_only=False, filters=None,
                            sort_by='primary_payment', sort_order='desc',
                            limit=None, offset=0):
    select_cols = "COUNT(*)" if count_only else """
        b.id,
        b.patient_name,
        b.referring_doctor,
        b.scan_type,
        b.insurance_carrier,
        b.modality,
        b.service_date,
        b.primary_payment,
        b.secondary_payment,
        b.total_payment,
        b.billed_amount
    """

    sql = f"""SELECT {select_cols}
        FROM billing_records b
        JOIN payers p ON b.insurance_carrier = p.code
        WHERE b.primary_payment > 0
          AND b.secondary_payment = 0
          AND p.expected_has_secondary = 1
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
        sort_col = SORTABLE_COLUMNS.get(sort_by, 'b.primary_payment')
        direction = 'ASC' if sort_order.upper() == 'ASC' else 'DESC'
        sql += f" ORDER BY {sort_col} {direction}"

        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

    return sql, params


@secondary_bp.route('/secondary-followup')
def secondary_followup_page():
    return render_template('secondary_queue.html')


@secondary_bp.route('/api/secondary-followup')
def api_secondary_followup():
    filters = {
        'carrier':   request.args.get('carrier'),
        'modality':  request.args.get('modality'),
        'date_from': request.args.get('date_from'),
        'date_to':   request.args.get('date_to'),
        'search':    request.args.get('search'),
    }
    sort_by = request.args.get('sort_by', 'primary_payment')
    sort_order = request.args.get('sort_order', 'desc')
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(200, max(1, int(request.args.get('per_page', 50))))
    offset = (page - 1) * per_page

    db = get_db()

    count_sql, count_params = _build_secondary_query(count_only=True, filters=filters)
    total = db.execute(count_sql, count_params).fetchone()[0]

    data_sql, data_params = _build_secondary_query(
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


@secondary_bp.route('/api/secondary-followup/filters')
def api_secondary_filters():
    db = get_db()
    carriers = [r[0] for r in db.execute("""
        SELECT DISTINCT b.insurance_carrier
        FROM billing_records b
        JOIN payers p ON b.insurance_carrier = p.code
        WHERE b.primary_payment > 0 AND b.secondary_payment = 0 AND p.expected_has_secondary = 1
        ORDER BY b.insurance_carrier
    """).fetchall()]
    modalities = [r[0] for r in db.execute("""
        SELECT DISTINCT b.modality
        FROM billing_records b
        JOIN payers p ON b.insurance_carrier = p.code
        WHERE b.primary_payment > 0 AND b.secondary_payment = 0 AND p.expected_has_secondary = 1
        ORDER BY b.modality
    """).fetchall()]
    return jsonify({'carriers': carriers, 'modalities': modalities})
