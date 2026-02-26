"""F-02: X12 835 ERA (Electronic Remittance Advice) Parser

Parses ANSI X12 835 transaction files to extract payment and claim data.

Segment reference:
  ISA - Interchange control header
  GS  - Functional group header
  ST  - Transaction set header (835)
  BPR - Financial information (payment method, amount, date)
  TRN - Reassociation trace (check/EFT number)
  N1  - Party identification (PR=payer, PE=payee)
  CLP - Claim payment information
  SVC - Service payment information
  CAS - Claims adjustment
  DTM - Date/time reference
  SE  - Transaction set trailer
  GE  - Functional group trailer
  IEA - Interchange control trailer
"""
import os
from datetime import datetime, date
from flask import request, jsonify
from app.parser import parser_bp
from app.models import db, EraPayment, EraClaimLine


def parse_date(date_str):
    """Parse X12 date format CCYYMMDD to Python date."""
    if not date_str or len(date_str) < 8:
        return None
    try:
        return datetime.strptime(date_str[:8], '%Y%m%d').date()
    except ValueError:
        return None


def parse_amount(amount_str):
    """Parse amount string to float."""
    if not amount_str:
        return 0.0
    try:
        return float(amount_str)
    except (ValueError, TypeError):
        return 0.0


def parse_835_content(content, filename='unknown'):
    """Parse raw 835 file content string.

    Returns a dict with payment header info and list of claim lines.
    """
    # Detect segment delimiter (usually ~ but can vary)
    # Element separator is usually * but detect from ISA
    element_sep = '*'
    segment_sep = '~'

    # Clean up content
    content = content.replace('\r\n', '').replace('\n', '').replace('\r', '')

    segments = [s.strip() for s in content.split(segment_sep) if s.strip()]

    payment_info = {
        'filename': filename,
        'payment_method': None,
        'payment_amount': 0.0,
        'payment_date': None,
        'check_eft_number': None,
        'payer_name': None,
    }

    claims = []
    current_claim = None
    current_svc = None

    for segment in segments:
        elements = segment.split(element_sep)
        seg_id = elements[0].strip()

        if seg_id == 'BPR':
            # BPR*payment_method*amount*...*date
            if len(elements) > 1:
                payment_info['payment_method'] = elements[1]
            if len(elements) > 2:
                payment_info['payment_amount'] = parse_amount(elements[2])
            # Payment date is typically at BPR16 (index 16) but can vary;
            # scan backwards from the end for an 8-digit date string
            for i in range(len(elements) - 1, 2, -1):
                d = parse_date(elements[i])
                if d is not None:
                    payment_info['payment_date'] = d
                    break

        elif seg_id == 'TRN':
            # TRN*1*check_number*...
            if len(elements) > 2:
                payment_info['check_eft_number'] = elements[2]

        elif seg_id == 'N1':
            # N1*PR*payer_name  (PR = payer)
            if len(elements) > 2 and elements[1] == 'PR':
                payment_info['payer_name'] = elements[2]

        elif seg_id == 'CLP':
            # CLP*claim_id*status*billed*paid*...*patient_name...
            # Save previous claim if exists
            if current_claim:
                claims.append(current_claim)

            current_claim = {
                'claim_id': elements[1] if len(elements) > 1 else None,
                'claim_status': elements[2] if len(elements) > 2 else None,
                'billed_amount': parse_amount(elements[3]) if len(elements) > 3 else 0.0,
                'paid_amount': parse_amount(elements[4]) if len(elements) > 4 else 0.0,
                'patient_name_835': None,
                'service_date_835': None,
                'cpt_code': None,
                'cas_group_code': None,
                'cas_reason_code': None,
                'cas_adjustment_amount': 0.0,
            }
            current_svc = None

        elif seg_id == 'NM1' and current_claim:
            # NM1*QC*1*LAST*FIRST*... (QC = patient)
            if len(elements) > 3 and elements[1] == 'QC':
                last = elements[3] if len(elements) > 3 else ''
                first = elements[4] if len(elements) > 4 else ''
                if last and first:
                    current_claim['patient_name_835'] = f'{last}, {first}'.upper()
                elif last:
                    current_claim['patient_name_835'] = last.upper()

        elif seg_id == 'DTM' and current_claim:
            # DTM*232*CCYYMMDD (232 = service date)
            # DTM*472*CCYYMMDD (472 = service period start)
            if len(elements) > 2 and elements[1] in ('232', '472'):
                current_claim['service_date_835'] = parse_date(elements[2])

        elif seg_id == 'SVC' and current_claim:
            # SVC*HC:CPT_CODE*billed*paid
            if len(elements) > 1:
                svc_id = elements[1]
                # Extract CPT from composite like HC:74177
                if ':' in svc_id:
                    current_claim['cpt_code'] = svc_id.split(':')[1]
                else:
                    current_claim['cpt_code'] = svc_id

        elif seg_id == 'CAS' and current_claim:
            # CAS*group*reason*amount*reason*amount...
            # Can have multiple reason/amount pairs
            if len(elements) > 3:
                current_claim['cas_group_code'] = elements[1]
                current_claim['cas_reason_code'] = elements[2]
                current_claim['cas_adjustment_amount'] = parse_amount(elements[3])

    # Don't forget the last claim
    if current_claim:
        claims.append(current_claim)

    return {
        'payment': payment_info,
        'claims': claims,
    }


def store_parsed_835(parsed_data):
    """Store parsed 835 data into the database."""
    payment_info = parsed_data['payment']

    era_payment = EraPayment(
        filename=payment_info['filename'],
        check_eft_number=payment_info['check_eft_number'],
        payment_amount=payment_info['payment_amount'],
        payment_date=payment_info['payment_date'],
        payment_method=payment_info['payment_method'],
        payer_name=payment_info['payer_name'],
    )
    db.session.add(era_payment)
    db.session.flush()  # Get the ID

    for claim in parsed_data['claims']:
        claim_line = EraClaimLine(
            era_payment_id=era_payment.id,
            claim_id=claim['claim_id'],
            claim_status=claim['claim_status'],
            billed_amount=claim['billed_amount'],
            paid_amount=claim['paid_amount'],
            patient_name_835=claim['patient_name_835'],
            service_date_835=claim['service_date_835'],
            cpt_code=claim['cpt_code'],
            cas_group_code=claim['cas_group_code'],
            cas_reason_code=claim['cas_reason_code'],
            cas_adjustment_amount=claim['cas_adjustment_amount'],
        )
        db.session.add(claim_line)

    db.session.commit()
    return era_payment


def parse_835_file(filepath):
    """Parse a single 835 file from disk."""
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    filename = os.path.basename(filepath)
    parsed = parse_835_content(content, filename)
    era_payment = store_parsed_835(parsed)
    return {
        'filename': filename,
        'claims_found': len(parsed['claims']),
        'payment_amount': parsed['payment']['payment_amount'],
        'era_payment_id': era_payment.id,
    }


def parse_835_folder(folder_path):
    """Parse all 835/EDI files in a folder."""
    results = []
    for fname in os.listdir(folder_path):
        if fname.lower().endswith(('.835', '.edi', '.txt')):
            fpath = os.path.join(folder_path, fname)
            try:
                result = parse_835_file(fpath)
                results.append(result)
            except Exception as e:
                results.append({'filename': fname, 'error': str(e)})
    return results


@parser_bp.route('/import/835', methods=['POST'])
def import_835():
    """POST /api/import/835 - Parse 835 file(s)"""
    # Check for file upload
    if 'file' in request.files:
        file = request.files['file']
        if not file.filename:
            return jsonify({'error': 'No file selected'}), 400

        content = file.read().decode('utf-8', errors='replace')
        parsed = parse_835_content(content, file.filename)
        era_payment = store_parsed_835(parsed)
        return jsonify({
            'files_parsed': 1,
            'claims_found': len(parsed['claims']),
            'payments_total': parsed['payment']['payment_amount'],
        })

    # Check for folder path in JSON body
    data = request.get_json(silent=True)
    if data and 'folder_path' in data:
        folder_path = data['folder_path']
        if not os.path.isdir(folder_path):
            return jsonify({'error': f'Folder not found: {folder_path}'}), 400
        results = parse_835_folder(folder_path)
        total_claims = sum(r.get('claims_found', 0) for r in results)
        total_payments = sum(r.get('payment_amount', 0) for r in results)
        return jsonify({
            'files_parsed': len(results),
            'claims_found': total_claims,
            'payments_total': total_payments,
            'details': results,
        })

    return jsonify({'error': 'Provide a file upload or folder_path in JSON body'}), 400


@parser_bp.route('/era/payments', methods=['GET'])
def list_era_payments():
    """GET /api/era/payments - List ERA payments with pagination and filters"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    payer = request.args.get('payer')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')

    query = EraPayment.query
    if payer:
        query = query.filter(EraPayment.payer_name.ilike(f'%{payer}%'))
    if date_from:
        query = query.filter(EraPayment.payment_date >= date_from)
    if date_to:
        query = query.filter(EraPayment.payment_date <= date_to)

    query = query.order_by(EraPayment.payment_date.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'payments': [p.to_dict() for p in pagination.items],
        'total': pagination.total,
        'page': page,
        'pages': pagination.pages,
    })


@parser_bp.route('/era/claims/<int:claim_id>', methods=['GET'])
def get_era_claim(claim_id):
    """GET /api/era/claims/<id> - Single claim detail"""
    claim = EraClaimLine.query.get_or_404(claim_id)
    return jsonify(claim.to_dict())
