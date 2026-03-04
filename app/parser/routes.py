"""835 ERA parser API routes (F-02)."""

import os

from flask import request, jsonify, current_app
from werkzeug.utils import secure_filename

from app.parser import bp
from app.extensions import db
from app.models import EraPayment, EraClaimLine
from app.utils import allowed_file, parse_pagination, paginate_query

from ocdr.era_835_parser import parse_835_file, parse_835_folder


ERA_EXTENSIONS = {'.835', '.edi'}


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
    parse_errors = []

    # Option 1: File upload
    if request.files:
        for key in request.files:
            file = request.files[key]
            if not file.filename:
                continue
            if not allowed_file(file.filename, ERA_EXTENSIONS):
                continue

            filename = secure_filename(file.filename)
            upload_dir = current_app.config['UPLOAD_FOLDER']
            filepath = os.path.join(upload_dir, filename)
            file.save(filepath)

            try:
                parsed = parse_835_file(filepath)
            except Exception as e:
                parse_errors.append({'file': filename, 'error': str(e)})
                try:
                    os.remove(filepath)
                except OSError:
                    pass
                continue

            _store_parsed_835(parsed)
            files_parsed += 1
            claims_found += len(parsed.get('claims', []))
            total_payment += float(parsed.get('payment', {}).get('amount', 0))

    # Option 2: Folder path in JSON body
    elif request.is_json:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Empty JSON body'}), 400
        folder_path = data.get('folder_path', '').strip()
        if not folder_path or not os.path.isdir(folder_path):
            return jsonify({'error': 'Invalid or missing folder_path'}), 400

        try:
            parsed_list = parse_835_folder(folder_path)
        except Exception as e:
            return jsonify({'error': f'Failed to parse 835 folder: {str(e)}'}), 422

        for parsed in parsed_list:
            _store_parsed_835(parsed)
            files_parsed += 1
            claims_found += len(parsed.get('claims', []))
            total_payment += float(parsed.get('payment', {}).get('amount', 0))
    else:
        return jsonify({'error': 'Provide file upload(s) or JSON body with folder_path'}), 400

    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': f'Database error: {str(e)}'}), 500

    result = {
        'files_parsed': files_parsed,
        'claims_found': claims_found,
        'payments_total': round(total_payment, 2),
    }
    if parse_errors:
        result['parse_errors'] = parse_errors

    return jsonify(result)


@bp.route('/era/payments', methods=['GET'])
def list_era_payments():
    """Paginated list of ERA payments with optional filters."""
    page, per_page = parse_pagination()

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
    return jsonify(paginate_query(query, page, per_page))


@bp.route('/era/claims/<int:claim_id>', methods=['GET'])
def get_claim_detail(claim_id):
    """Return a single ERA claim line with parent payment info."""
    claim = db.session.get(EraClaimLine, claim_id)
    if claim is None:
        return jsonify({'error': 'Claim not found'}), 404
    result = claim.to_dict()
    result['payment'] = claim.era_payment.to_dict()
    return jsonify(result)
