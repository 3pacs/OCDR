"""F-04: Denial Tracking & Appeal Queue.

Provides the priority appeal queue with server-side sorting by any column,
filtering, and status management for denied claims.
"""

import math
from datetime import date, datetime
from flask import Blueprint, jsonify, request, render_template

from app import get_db

denial_bp = Blueprint('denials', __name__)

# Columns that are valid sort targets, mapped to their SQL expressions.
SORTABLE_COLUMNS = {
    'patient_name':       'b.patient_name',
    'insurance_carrier':  'b.insurance_carrier',
    'modality':           'b.modality',
    'scan_type':          'b.scan_type',
    'service_date':       'b.service_date',
    'billed_amount':      'b.billed_amount',
    'total_payment':      'b.total_payment',
    'denial_status':      'b.denial_status',
    'denial_reason_code': 'b.denial_reason_code',
    'appeal_deadline':    'b.appeal_deadline',
    'days_old':           'days_old',
    'recoverability_score': 'recoverability_score',
    'referring_doctor':   'b.referring_doctor',
    'reading_physician':  'b.reading_physician',
    'description':        'b.description',
}


def _build_denial_query(*, count_only=False, filters=None, sort_by='recoverability_score',
                        sort_order='desc', limit=None, offset=0):
    """Build the SQL query for denied claims with dynamic sorting.

    Returns (sql, params) tuple.
    """
    today = date.today().isoformat()

    select_cols = "COUNT(*)" if count_only else """
        b.id,
        b.patient_name,
        b.referring_doctor,
        b.scan_type,
        b.insurance_carrier,
        b.modality,
        b.service_date,
        b.billed_amount,
        b.total_payment,
        b.denial_status,
        b.denial_reason_code,
        b.appeal_deadline,
        b.reading_physician,
        b.description,
        CAST(julianday(?) - julianday(b.service_date) AS INTEGER) AS days_old,
        ROUND(b.billed_amount * MAX(0, 1.0 - (julianday(?) - julianday(b.service_date)) / 365.0), 2) AS recoverability_score
    """

    sql = f"SELECT {select_cols} FROM billing_records b WHERE "
    conditions = ["(b.denial_status IS NOT NULL OR b.total_payment = 0)"]
    # By default, hide WRITTEN_OFF claims unless explicitly requested
    if not filters or filters.get('status') != 'WRITTEN_OFF':
        if not filters or not filters.get('include_written_off'):
            conditions.append("(b.denial_status IS NULL OR b.denial_status != 'WRITTEN_OFF')")
    params = [] if count_only else [today, today]

    if filters:
        if filters.get('status'):
            conditions.append("b.denial_status = ?")
            params.append(filters['status'])
        if filters.get('carrier'):
            conditions.append("b.insurance_carrier = ?")
            params.append(filters['carrier'])
        if filters.get('modality'):
            conditions.append("b.modality = ?")
            params.append(filters['modality'])
        if filters.get('date_from'):
            conditions.append("b.service_date >= ?")
            params.append(filters['date_from'])
        if filters.get('date_to'):
            conditions.append("b.service_date <= ?")
            params.append(filters['date_to'])
        if filters.get('search'):
            conditions.append("(b.patient_name LIKE ? OR b.referring_doctor LIKE ?)")
            term = f"%{filters['search']}%"
            params.extend([term, term])

    sql += " AND ".join(conditions)

    if not count_only:
        # Validate sort column to prevent SQL injection
        sort_col = SORTABLE_COLUMNS.get(sort_by, 'recoverability_score')
        direction = 'ASC' if sort_order.upper() == 'ASC' else 'DESC'
        sql += f" ORDER BY {sort_col} {direction}"

        if limit:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])

    return sql, params


# ── HTML views ────────────────────────────────────────────────────────

@denial_bp.route('/denials')
def denial_queue_page():
    """Render the denial queue page with sortable table."""
    return render_template('denial_queue.html')


@denial_bp.route('/denials/<int:denial_id>')
def denial_detail_page(denial_id):
    """Render the denial detail page."""
    db = get_db()
    today = date.today().isoformat()
    row = db.execute("""
        SELECT
            b.*,
            CAST(julianday(?) - julianday(b.service_date) AS INTEGER) AS days_old,
            ROUND(b.billed_amount * MAX(0, 1.0 - (julianday(?) - julianday(b.service_date)) / 365.0), 2) AS recoverability_score
        FROM billing_records b
        WHERE b.id = ?
    """, [today, today, denial_id]).fetchone()

    if not row:
        return "Claim not found", 404

    return render_template('denial_detail.html', claim=dict(row))


# ── JSON API endpoints ────────────────────────────────────────────────

@denial_bp.route('/api/denials')
def api_denials():
    """All denials with filters and sorting.

    Query params:
        status    – filter by denial_status
        carrier   – filter by insurance_carrier
        modality  – filter by modality
        date_from – service date range start
        date_to   – service date range end
        search    – text search on patient_name / referring_doctor
        sort_by   – any column key from SORTABLE_COLUMNS
        sort_order – asc | desc (default: desc)
        page      – 1-based page number (default: 1)
        per_page  – rows per page (default: 50, max: 200)
    """
    filters = {
        'status':    request.args.get('status'),
        'carrier':   request.args.get('carrier'),
        'modality':  request.args.get('modality'),
        'date_from': request.args.get('date_from'),
        'date_to':   request.args.get('date_to'),
        'search':    request.args.get('search'),
    }
    sort_by = request.args.get('sort_by', 'recoverability_score')
    sort_order = request.args.get('sort_order', 'desc')
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(200, max(1, int(request.args.get('per_page', 50))))
    offset = (page - 1) * per_page

    db = get_db()

    # Total count
    count_sql, count_params = _build_denial_query(count_only=True, filters=filters)
    total = db.execute(count_sql, count_params).fetchone()[0]

    # Data page
    data_sql, data_params = _build_denial_query(
        filters=filters,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=per_page,
        offset=offset,
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


@denial_bp.route('/api/denials/queue')
def api_denial_queue():
    """Priority appeal queue – same as /api/denials but with curated defaults.

    Defaults to recoverability_score DESC, limit 50.
    Accepts all the same sort/filter params as /api/denials.
    """
    filters = {
        'status':    request.args.get('status'),
        'carrier':   request.args.get('carrier'),
        'modality':  request.args.get('modality'),
        'date_from': request.args.get('date_from'),
        'date_to':   request.args.get('date_to'),
        'search':    request.args.get('search'),
    }
    sort_by = request.args.get('sort_by', 'recoverability_score')
    sort_order = request.args.get('sort_order', 'desc')
    limit = min(200, max(1, int(request.args.get('limit', 50))))

    db = get_db()
    data_sql, data_params = _build_denial_query(
        filters=filters,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
    )
    rows = db.execute(data_sql, data_params).fetchall()

    return jsonify({
        'data': [dict(r) for r in rows],
        'count': len(rows),
        'sort_by': sort_by,
        'sort_order': sort_order,
        'sortable_columns': list(SORTABLE_COLUMNS.keys()),
    })


@denial_bp.route('/api/denials/<int:denial_id>/appeal', methods=['POST'])
def api_appeal(denial_id):
    """Mark a denied claim as appealed."""
    db = get_db()
    body = request.get_json(force=True) if request.data else {}
    notes = body.get('notes', '')
    appeal_date = body.get('appeal_date', date.today().isoformat())

    result = db.execute(
        "UPDATE billing_records SET denial_status = 'APPEALED' WHERE id = ? AND denial_status = 'DENIED'",
        [denial_id],
    )
    db.commit()

    if result.rowcount == 0:
        return jsonify({'error': 'Claim not found or not in DENIED status'}), 404

    return jsonify({'id': denial_id, 'status': 'APPEALED', 'appeal_date': appeal_date, 'notes': notes})


@denial_bp.route('/api/denials/<int:denial_id>/resolve', methods=['POST'])
def api_resolve(denial_id):
    """Resolve a denial (PAID or WRITTEN_OFF)."""
    db = get_db()
    body = request.get_json(force=True) if request.data else {}
    resolution = body.get('resolution', 'WRITTEN_OFF')
    amount = body.get('amount', 0)

    if resolution not in ('PAID', 'WRITTEN_OFF'):
        return jsonify({'error': 'resolution must be PAID or WRITTEN_OFF'}), 400

    status = 'RESOLVED' if resolution == 'PAID' else 'WRITTEN_OFF'
    result = db.execute(
        "UPDATE billing_records SET denial_status = ?, total_payment = total_payment + ? WHERE id = ?",
        [status, amount, denial_id],
    )
    db.commit()

    if result.rowcount == 0:
        return jsonify({'error': 'Claim not found'}), 404

    return jsonify({'id': denial_id, 'status': status, 'resolution': resolution, 'amount': amount})


@denial_bp.route('/api/denials/<int:denial_id>/writeoff', methods=['POST'])
def api_writeoff(denial_id):
    """Write off a claim – removes it from active alert lists."""
    db = get_db()
    # Store the previous status so it can be undone
    row = db.execute("SELECT denial_status FROM billing_records WHERE id = ?", [denial_id]).fetchone()
    if not row:
        return jsonify({'error': 'Claim not found'}), 404

    previous_status = row['denial_status']
    db.execute(
        "UPDATE billing_records SET denial_status = 'WRITTEN_OFF' WHERE id = ?",
        [denial_id],
    )
    db.commit()
    return jsonify({'id': denial_id, 'status': 'WRITTEN_OFF', 'previous_status': previous_status})


@denial_bp.route('/api/denials/<int:denial_id>/undo-writeoff', methods=['POST'])
def api_undo_writeoff(denial_id):
    """Undo a write-off – restore the claim back to DENIED status."""
    db = get_db()
    body = request.get_json(force=True) if request.data else {}
    restore_to = body.get('restore_to', 'DENIED')

    if restore_to not in ('DENIED', 'APPEALED'):
        restore_to = 'DENIED'

    result = db.execute(
        "UPDATE billing_records SET denial_status = ? WHERE id = ? AND denial_status = 'WRITTEN_OFF'",
        [restore_to, denial_id],
    )
    db.commit()

    if result.rowcount == 0:
        return jsonify({'error': 'Claim not found or not in WRITTEN_OFF status'}), 404

    return jsonify({'id': denial_id, 'status': restore_to})


@denial_bp.route('/api/denials/bulk-writeoff', methods=['POST'])
def api_bulk_writeoff():
    """Write off multiple claims at once."""
    db = get_db()
    body = request.get_json(force=True)
    ids = body.get('ids', [])

    if not ids:
        return jsonify({'error': 'No claim IDs provided'}), 400

    placeholders = ','.join('?' for _ in ids)
    db.execute(
        f"UPDATE billing_records SET denial_status = 'WRITTEN_OFF' WHERE id IN ({placeholders})",
        ids,
    )
    db.commit()
    return jsonify({'written_off': len(ids)})


@denial_bp.route('/api/denials/bulk-undo-writeoff', methods=['POST'])
def api_bulk_undo_writeoff():
    """Undo write-off for multiple claims."""
    db = get_db()
    body = request.get_json(force=True)
    ids = body.get('ids', [])

    if not ids:
        return jsonify({'error': 'No claim IDs provided'}), 400

    placeholders = ','.join('?' for _ in ids)
    db.execute(
        f"UPDATE billing_records SET denial_status = 'DENIED' WHERE id IN ({placeholders}) AND denial_status = 'WRITTEN_OFF'",
        ids,
    )
    db.commit()
    return jsonify({'restored': len(ids)})


@denial_bp.route('/api/denials/written-off')
def api_written_off():
    """View all written-off claims – for searching/undoing write-offs."""
    filters = {
        'status':    'WRITTEN_OFF',
        'carrier':   request.args.get('carrier'),
        'modality':  request.args.get('modality'),
        'date_from': request.args.get('date_from'),
        'date_to':   request.args.get('date_to'),
        'search':    request.args.get('search'),
        'include_written_off': True,
    }
    sort_by = request.args.get('sort_by', 'service_date')
    sort_order = request.args.get('sort_order', 'desc')
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(200, max(1, int(request.args.get('per_page', 50))))
    offset = (page - 1) * per_page

    db = get_db()

    count_sql, count_params = _build_denial_query(count_only=True, filters=filters)
    total = db.execute(count_sql, count_params).fetchone()[0]

    data_sql, data_params = _build_denial_query(
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
    })


@denial_bp.route('/denials/written-off')
def written_off_page():
    """HTML page for viewing/searching written-off claims with undo."""
    return render_template('written_off.html')


@denial_bp.route('/api/denials/filters')
def api_denial_filters():
    """Return distinct values for filter dropdowns."""
    db = get_db()
    carriers = [r[0] for r in db.execute(
        "SELECT DISTINCT insurance_carrier FROM billing_records WHERE denial_status IS NOT NULL OR total_payment = 0 ORDER BY insurance_carrier"
    ).fetchall()]
    modalities = [r[0] for r in db.execute(
        "SELECT DISTINCT modality FROM billing_records WHERE denial_status IS NOT NULL OR total_payment = 0 ORDER BY modality"
    ).fetchall()]
    statuses = [r[0] for r in db.execute(
        "SELECT DISTINCT denial_status FROM billing_records WHERE denial_status IS NOT NULL ORDER BY denial_status"
    ).fetchall()]

    return jsonify({
        'carriers': carriers,
        'modalities': modalities,
        'statuses': statuses,
    })
