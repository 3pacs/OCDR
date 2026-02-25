"""F-06: Timely Filing Deadline Tracker.

Tracks appeal deadlines and flags claims approaching or past their filing limits.
Fully sortable and filterable.
"""

import math
from datetime import date
from flask import Blueprint, jsonify, request, render_template

from app import get_db

filing_bp = Blueprint('filing_deadlines', __name__)

SORTABLE_COLUMNS = {
    'patient_name':      'b.patient_name',
    'insurance_carrier': 'b.insurance_carrier',
    'modality':          'b.modality',
    'service_date':      'b.service_date',
    'appeal_deadline':   'b.appeal_deadline',
    'days_remaining':    'days_remaining',
    'billed_amount':     'b.billed_amount',
    'total_payment':     'b.total_payment',
    'filing_status':     'filing_status',
    'referring_doctor':  'b.referring_doctor',
    'scan_type':         'b.scan_type',
}


def _build_deadline_query(*, count_only=False, filters=None,
                           sort_by='days_remaining', sort_order='asc',
                           limit=None, offset=0):
    today = date.today().isoformat()

    select_cols = "COUNT(*)" if count_only else f"""
        b.id,
        b.patient_name,
        b.referring_doctor,
        b.scan_type,
        b.insurance_carrier,
        b.modality,
        b.service_date,
        b.billed_amount,
        b.total_payment,
        b.appeal_deadline,
        b.denial_status,
        CAST(julianday(b.appeal_deadline) - julianday('{today}') AS INTEGER) AS days_remaining,
        CASE
            WHEN julianday(b.appeal_deadline) < julianday('{today}') THEN 'PAST_DEADLINE'
            WHEN julianday(b.appeal_deadline) - julianday('{today}') <= 30 THEN 'WARNING_30DAY'
            ELSE 'SAFE'
        END AS filing_status
    """

    sql = f"""SELECT {select_cols}
        FROM billing_records b
        WHERE b.total_payment = 0
          AND b.appeal_deadline IS NOT NULL
          AND (b.denial_status IS NULL OR b.denial_status NOT IN ('RESOLVED', 'WRITTEN_OFF'))
    """
    params = []

    if filters:
        if filters.get('filing_status'):
            if filters['filing_status'] == 'PAST_DEADLINE':
                sql += f" AND julianday(b.appeal_deadline) < julianday('{today}')"
            elif filters['filing_status'] == 'WARNING_30DAY':
                sql += f" AND julianday(b.appeal_deadline) >= julianday('{today}') AND julianday(b.appeal_deadline) - julianday('{today}') <= 30"
            elif filters['filing_status'] == 'SAFE':
                sql += f" AND julianday(b.appeal_deadline) - julianday('{today}') > 30"
        if filters.get('carrier'):
            sql += " AND b.insurance_carrier = ?"
            params.append(filters['carrier'])
        if filters.get('modality'):
            sql += " AND b.modality = ?"
            params.append(filters['modality'])
        if filters.get('search'):
            sql += " AND (b.patient_name LIKE ? OR b.referring_doctor LIKE ?)"
            term = f"%{filters['search']}%"
            params.extend([term, term])

    if not count_only:
        sort_col = SORTABLE_COLUMNS.get(sort_by, 'days_remaining')
        direction = 'ASC' if sort_order.upper() == 'ASC' else 'DESC'
        sql += f" ORDER BY {sort_col} {direction}"

        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

    return sql, params


@filing_bp.route('/filing-deadlines')
def filing_deadlines_page():
    return render_template('filing_deadlines.html')


@filing_bp.route('/api/filing-deadlines')
def api_filing_deadlines():
    filters = {
        'filing_status': request.args.get('status'),
        'carrier':       request.args.get('carrier'),
        'modality':      request.args.get('modality'),
        'search':        request.args.get('search'),
    }
    sort_by = request.args.get('sort_by', 'days_remaining')
    sort_order = request.args.get('sort_order', 'asc')
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(200, max(1, int(request.args.get('per_page', 50))))
    offset = (page - 1) * per_page

    db = get_db()

    count_sql, count_params = _build_deadline_query(count_only=True, filters=filters)
    total = db.execute(count_sql, count_params).fetchone()[0]

    data_sql, data_params = _build_deadline_query(
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


@filing_bp.route('/api/filing-deadlines/alerts')
def api_filing_alerts():
    db = get_db()
    today = date.today().isoformat()

    past = db.execute(f"""
        SELECT COUNT(*) FROM billing_records
        WHERE total_payment = 0 AND appeal_deadline IS NOT NULL
          AND julianday(appeal_deadline) < julianday('{today}')
          AND (denial_status IS NULL OR denial_status NOT IN ('RESOLVED','WRITTEN_OFF'))
    """).fetchone()[0]

    warning = db.execute(f"""
        SELECT COUNT(*) FROM billing_records
        WHERE total_payment = 0 AND appeal_deadline IS NOT NULL
          AND julianday(appeal_deadline) >= julianday('{today}')
          AND julianday(appeal_deadline) - julianday('{today}') <= 30
          AND (denial_status IS NULL OR denial_status NOT IN ('RESOLVED','WRITTEN_OFF'))
    """).fetchone()[0]

    return jsonify({
        'past_deadline': past,
        'warning': warning,
    })


@filing_bp.route('/api/filing-deadlines/filters')
def api_filing_filters():
    db = get_db()
    carriers = [r[0] for r in db.execute(
        "SELECT DISTINCT insurance_carrier FROM billing_records WHERE total_payment = 0 AND appeal_deadline IS NOT NULL ORDER BY insurance_carrier"
    ).fetchall()]
    modalities = [r[0] for r in db.execute(
        "SELECT DISTINCT modality FROM billing_records WHERE total_payment = 0 AND appeal_deadline IS NOT NULL ORDER BY modality"
    ).fetchall()]
    return jsonify({
        'carriers': carriers,
        'modalities': modalities,
        'statuses': ['PAST_DEADLINE', 'WARNING_30DAY', 'SAFE'],
    })
