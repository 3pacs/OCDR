"""835 ERA parser API routes (F-02)."""

import os
from datetime import datetime

from flask import request, jsonify, current_app
from werkzeug.utils import secure_filename

from app.parser import bp
from app.extensions import db
from app.models import EraPayment, EraClaimLine

from ocdr.era_835_parser import parse_835_file, parse_835_folder


ALLOWED_EXTENSIONS = {'.835', '.edi'}


def _allowed_file(filename):
    return os.path.splitext(filename)[1].lower() in ALLOWED_EXTENSIONS


def _store_parsed_835(parsed: dict) -> EraPayment:
    """Convert a parsed 835 dict into EraPayment + EraClaimLine models."""
    payment_info = parsed.get('payment', {})

    era = EraPayment(
        filename=parsed.get('file', ''),
        check_eft_number=parsed.get('check_eft_number', ''),
        payment_amount=payment_info.get('amount', 0),
        payment_date=payment_info.get('date'),
        payment_method=payment_info.get('method', ''),
        payer_name=parsed.get('payer_name', ''),
    )
    db.session.add(era)
    db.session.flush()  # get era.id

    for claim in parsed.get('claims', []):
        # Extract first CPT code from service lines
        svc_lines = claim.get('service_lines', [])
        cpt = svc_lines[0].get('cpt_code', '') if svc_lines else ''

        # Extract first CAS adjustment
        adjustments = claim.get('adjustments', [])
        cas_group = ''
        cas_reason = ''
        cas_amount = None
        if adjustments:
            cas_group = adjustments[0].get('group_code', '')
            inner = adjustments[0].get('adjustments', [])
            if inner:
                cas_reason = inner[0].get('reason_code', '')
                cas_amount = inner[0].get('amount')

        line = EraClaimLine(
            era_payment_id=era.id,
            claim_id=claim.get('claim_id', ''),
            claim_status=claim.get('claim_status', ''),
            billed_amount=claim.get('billed_amount', 0),
            paid_amount=claim.get('paid_amount', 0),
            patient_name_835=claim.get('patient_name', ''),
            service_date_835=claim.get('service_date'),
            cpt_code=cpt,
            cas_group_code=cas_group,
            cas_reason_code=cas_reason,
            cas_adjustment_amount=cas_amount,
        )
        db.session.add(line)

    return era


@bp.route('/import/835', methods=['POST'])
def import_835():
    """Import 835 ERA files — either uploaded file(s) or a folder path."""
    files_parsed = 0
    claims_found = 0
    total_payment = 0.0

    # Option 1: File upload
    if request.files:
        for key in request.files:
            file = request.files[key]
            if not file.filename:
                continue
            if not _allowed_file(file.filename):
                continue

            filename = secure_filename(file.filename)
            upload_dir = current_app.config['UPLOAD_FOLDER']
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)

            parsed = parse_835_file(filepath)
            era = _store_parsed_835(parsed)
            files_parsed += 1
            claims_found += len(parsed.get('claims', []))
            total_payment += float(parsed.get('payment', {}).get('amount', 0))

    # Option 2: Folder path in JSON body
    elif request.is_json:
        data = request.get_json()
        folder_path = data.get('folder_path', '')
        if not folder_path or not os.path.isdir(folder_path):
            return jsonify({'error': 'Invalid or missing folder_path'}), 400

        parsed_list = parse_835_folder(folder_path)
        for parsed in parsed_list:
            era = _store_parsed_835(parsed)
            files_parsed += 1
            claims_found += len(parsed.get('claims', []))
            total_payment += float(parsed.get('payment', {}).get('amount', 0))
    else:
        return jsonify({'error': 'Provide file upload(s) or JSON body with folder_path'}), 400

    db.session.commit()

    return jsonify({
        'files_parsed': files_parsed,
        'claims_found': claims_found,
        'payments_total': round(total_payment, 2),
    })


@bp.route('/era/payments', methods=['GET'])
def list_era_payments():
    """Paginated list of ERA payments with optional filters."""
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)

    query = EraPayment.query

    payer = request.args.get('payer')
    if payer:
        query = query.filter(EraPayment.payer_name.ilike(f'%{payer}%'))

    date_from = request.args.get('date_from')
    if date_from:
        query = query.filter(EraPayment.payment_date >= date_from)

    date_to = request.args.get('date_to')
    if date_to:
        query = query.filter(EraPayment.payment_date <= date_to)

    query = query.order_by(EraPayment.parsed_at.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'items': [p.to_dict() for p in pagination.items],
        'total': pagination.total,
        'page': pagination.page,
        'per_page': pagination.per_page,
        'pages': pagination.pages,
    })


@bp.route('/era/claims/<int:claim_id>', methods=['GET'])
def get_claim_detail(claim_id):
    """Return a single ERA claim line with parent payment info."""
    claim = EraClaimLine.query.get_or_404(claim_id)
    result = claim.to_dict()
    result['payment'] = claim.era_payment.to_dict()
    return jsonify(result)
