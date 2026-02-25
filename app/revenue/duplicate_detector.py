"""F-08: Duplicate Claim Detector.

Finds duplicate claims (same patient+date+scan+modality), excluding C.A.P exceptions.
Fully sortable and filterable.
"""

import math
from flask import Blueprint, jsonify, request, render_template

from app import get_db

duplicate_bp = Blueprint('duplicates', __name__)

SORTABLE_COLUMNS = {
    'patient_name':      'b.patient_name',
    'insurance_carrier': 'b.insurance_carrier',
    'modality':          'b.modality',
    'scan_type':         'b.scan_type',
    'service_date':      'b.service_date',
    'total_payment':     'b.total_payment',
    'referring_doctor':  'b.referring_doctor',
    'billed_amount':     'b.billed_amount',
    'dup_count':         'dup_count',
}


@duplicate_bp.route('/duplicates')
def duplicates_page():
    return render_template('duplicates.html')


@duplicate_bp.route('/api/duplicates')
def api_duplicates():
    include_legitimate = request.args.get('include_legitimate', 'false').lower() == 'true'
    sort_by = request.args.get('sort_by', 'dup_count')
    sort_order = request.args.get('sort_order', 'desc')
    page = max(1, int(request.args.get('page', 1)))
    per_page = min(200, max(1, int(request.args.get('per_page', 50))))
    offset = (page - 1) * per_page
    search = request.args.get('search', '').strip()
    carrier = request.args.get('carrier')
    modality = request.args.get('modality')

    db = get_db()

    # Find groups of duplicates
    where_extra = ""
    params = []

    if not include_legitimate:
        where_extra += " AND (b.description IS NULL OR (UPPER(b.description) NOT LIKE '%C.A.P%' AND UPPER(b.description) NOT LIKE '%CAP%'))"

    if search:
        where_extra += " AND (b.patient_name LIKE ? OR b.referring_doctor LIKE ?)"
        term = f"%{search}%"
        params.extend([term, term])
    if carrier:
        where_extra += " AND b.insurance_carrier = ?"
        params.append(carrier)
    if modality:
        where_extra += " AND b.modality = ?"
        params.append(modality)

    sort_col = SORTABLE_COLUMNS.get(sort_by, 'dup_count')
    direction = 'ASC' if sort_order.upper() == 'ASC' else 'DESC'

    # Get duplicate groups
    count_sql = f"""
        SELECT COUNT(*) FROM (
            SELECT b.patient_name, b.service_date, b.scan_type, b.modality
            FROM billing_records b
            WHERE 1=1 {where_extra}
            GROUP BY b.patient_name, b.service_date, b.scan_type, b.modality
            HAVING COUNT(*) > 1
        )
    """
    total = db.execute(count_sql, params).fetchone()[0]

    data_sql = f"""
        SELECT
            b.patient_name,
            b.service_date,
            b.scan_type,
            b.modality,
            b.insurance_carrier,
            b.referring_doctor,
            COUNT(*) as dup_count,
            SUM(b.total_payment) as total_payment,
            SUM(b.billed_amount) as billed_amount,
            GROUP_CONCAT(b.id) as record_ids
        FROM billing_records b
        WHERE 1=1 {where_extra}
        GROUP BY b.patient_name, b.service_date, b.scan_type, b.modality
        HAVING COUNT(*) > 1
        ORDER BY {sort_col} {direction}
        LIMIT ? OFFSET ?
    """
    rows = db.execute(data_sql, params + [per_page, offset]).fetchall()

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


@duplicate_bp.route('/api/duplicates/<int:record_id>/legitimate', methods=['POST'])
def api_mark_legitimate(record_id):
    """Mark a duplicate as legitimate (not actually a duplicate)."""
    db = get_db()
    # Update description to include [LEGITIMATE] tag so it's excluded next time
    db.execute(
        "UPDATE billing_records SET description = COALESCE(description, '') || ' [LEGITIMATE_DUP]' WHERE id = ?",
        [record_id],
    )
    db.commit()
    return jsonify({'id': record_id, 'marked': 'legitimate'})


@duplicate_bp.route('/api/duplicates/filters')
def api_duplicate_filters():
    db = get_db()
    carriers = [r[0] for r in db.execute(
        "SELECT DISTINCT insurance_carrier FROM billing_records ORDER BY insurance_carrier"
    ).fetchall()]
    modalities = [r[0] for r in db.execute(
        "SELECT DISTINCT modality FROM billing_records ORDER BY modality"
    ).fetchall()]
    return jsonify({'carriers': carriers, 'modalities': modalities})
