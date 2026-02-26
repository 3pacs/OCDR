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
import hashlib
import os
from datetime import datetime, date
from flask import request, jsonify
from app.parser import parser_bp
from app.models import db, EraPayment, EraClaimLine

# File extensions recognized as potential EOB/ERA files
EOB_EXTENSIONS = {'.835', '.edi', '.txt'}


def file_content_hash(filepath):
    """Compute SHA-256 hash of file contents for duplicate detection."""
    h = hashlib.sha256()
    with open(filepath, 'rb') as f:
        for chunk in iter(lambda: f.read(8192), b''):
            h.update(chunk)
    return h.hexdigest()


def is_835_content(content):
    """Heuristic check: does this text look like an X12 835 file?

    Checks for key segment identifiers that appear in valid 835 files.
    This prevents importing random .txt files that aren't EOBs.
    """
    # Look for at least one of the mandatory 835 segments
    indicators = ('ISA*', 'BPR*', 'CLP*', 'ST*835')
    upper = content[:4000].upper()
    return any(ind in upper for ind in indicators)


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


def _claim_exists(claim):
    """Check if a claim already exists in era_claim_lines.

    Matches on claim_id + patient_name + service_date + paid_amount.
    This catches duplicate claims across files (e.g. same EOB delivered
    as both .835 and .txt by different vendors).
    """
    q = EraClaimLine.query.filter_by(claim_id=claim['claim_id'])
    if claim['patient_name_835']:
        q = q.filter_by(patient_name_835=claim['patient_name_835'])
    if claim['service_date_835']:
        q = q.filter_by(service_date_835=claim['service_date_835'])
    q = q.filter_by(paid_amount=claim['paid_amount'])
    return q.first() is not None


def store_parsed_835(parsed_data):
    """Store parsed 835 data into the database.

    Performs claim-level deduplication: each claim line is checked against
    existing era_claim_lines before insertion.  Returns a tuple of
    (era_payment, claims_new, claims_duplicate).
    """
    payment_info = parsed_data['payment']
    claims_new = 0
    claims_duplicate = 0

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
        if _claim_exists(claim):
            claims_duplicate += 1
            continue

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
        claims_new += 1

    # If every claim was a duplicate, remove the empty payment header
    if claims_new == 0 and claims_duplicate > 0:
        db.session.delete(era_payment)
        db.session.commit()
        return None, claims_new, claims_duplicate

    db.session.commit()
    return era_payment, claims_new, claims_duplicate


def parse_835_file(filepath):
    """Parse a single 835 file from disk.

    Returns a dict with import stats including claim-level dedup counts.
    """
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        content = f.read()
    filename = os.path.basename(filepath)
    parsed = parse_835_content(content, filename)
    era_payment, claims_new, claims_duplicate = store_parsed_835(parsed)
    result = {
        'filename': filename,
        'claims_found': len(parsed['claims']),
        'claims_new': claims_new,
        'claims_duplicate': claims_duplicate,
        'payment_amount': parsed['payment']['payment_amount'],
    }
    if era_payment is not None:
        result['era_payment_id'] = era_payment.id
    return result


def scan_eob_directory(folder_path):
    """Recursively find all potential EOB files in a directory tree.

    Returns a list of absolute file paths for files with recognized extensions.
    """
    found = []
    for dirpath, _dirnames, filenames in os.walk(folder_path):
        for fname in filenames:
            ext = os.path.splitext(fname)[1].lower()
            if ext in EOB_EXTENSIONS:
                found.append(os.path.join(dirpath, fname))
    return sorted(found)


def parse_835_folder(folder_path, recursive=True):
    """Parse all 835/EDI/text EOB files in a folder (optionally recursive).

    Deduplicates by:
      1. File content hash — if two files are byte-identical, only the first is imported.
      2. Database filename check — if the filename was already imported, skip it.
      3. 835 content heuristic — .txt files are only imported if they look like 835 data.
    """
    if recursive:
        file_paths = scan_eob_directory(folder_path)
    else:
        file_paths = []
        for fname in os.listdir(folder_path):
            ext = os.path.splitext(fname)[1].lower()
            if ext in EOB_EXTENSIONS:
                file_paths.append(os.path.join(folder_path, fname))
        file_paths.sort()

    results = []
    seen_hashes = set()
    # Pre-load already-imported filenames from DB to avoid re-importing
    already_imported = {
        ep.filename for ep in db.session.query(EraPayment.filename).all()
    }

    for fpath in file_paths:
        fname = os.path.basename(fpath)
        rel_path = os.path.relpath(fpath, folder_path)

        # Skip files already in the database (by filename)
        if fname in already_imported:
            results.append({
                'filename': rel_path,
                'status': 'skipped',
                'reason': 'already imported',
            })
            continue

        # Compute content hash for duplicate detection among files in this batch
        try:
            content_hash = file_content_hash(fpath)
        except OSError as e:
            results.append({'filename': rel_path, 'status': 'error', 'reason': str(e)})
            continue

        if content_hash in seen_hashes:
            results.append({
                'filename': rel_path,
                'status': 'skipped',
                'reason': 'duplicate content',
            })
            continue
        seen_hashes.add(content_hash)

        # For .txt files, verify content looks like 835 data before importing
        ext = os.path.splitext(fname)[1].lower()
        if ext == '.txt':
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as f:
                    preview = f.read(4000)
                if not is_835_content(preview):
                    results.append({
                        'filename': rel_path,
                        'status': 'skipped',
                        'reason': 'not 835 content',
                    })
                    continue
            except OSError as e:
                results.append({'filename': rel_path, 'status': 'error', 'reason': str(e)})
                continue

        # Parse the file and perform claim-level deduplication
        try:
            result = parse_835_file(fpath)
            result['filename'] = rel_path
            # If every claim in the file was a duplicate, mark the file as skipped
            if result['claims_new'] == 0 and result['claims_duplicate'] > 0:
                result['status'] = 'skipped'
                result['reason'] = 'duplicate claims'
            else:
                result['status'] = 'imported'
                already_imported.add(fname)  # track for this batch
            results.append(result)
        except Exception as e:
            results.append({'filename': rel_path, 'status': 'error', 'reason': str(e)})

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
        era_payment, claims_new, claims_duplicate = store_parsed_835(parsed)
        return jsonify({
            'files_parsed': 1,
            'claims_found': len(parsed['claims']),
            'claims_new': claims_new,
            'claims_duplicate': claims_duplicate,
            'payments_total': parsed['payment']['payment_amount'],
        })

    # Check for folder path in JSON body
    data = request.get_json(silent=True)
    if data and 'folder_path' in data:
        folder_path = data['folder_path']
        if not os.path.isdir(folder_path):
            return jsonify({'error': f'Folder not found: {folder_path}'}), 400
        recursive = data.get('recursive', True)
        results = parse_835_folder(folder_path, recursive=recursive)
        imported = [r for r in results if r.get('status') == 'imported']
        skipped = [r for r in results if r.get('status') == 'skipped']
        errors = [r for r in results if r.get('status') == 'error']
        total_claims = sum(r.get('claims_found', 0) for r in imported)
        total_payments = sum(r.get('payment_amount', 0) for r in imported)
        return jsonify({
            'files_parsed': len(imported),
            'files_skipped': len(skipped),
            'files_errored': len(errors),
            'claims_found': total_claims,
            'payments_total': total_payments,
            'details': results,
        })

    return jsonify({'error': 'Provide a file upload or folder_path in JSON body'}), 400


@parser_bp.route('/import/eob-scan', methods=['POST'])
def eob_scan():
    """POST /api/import/eob-scan - Scan an EOB directory recursively.

    JSON body: { "folder_path": "X:\\EOBS" }

    Recursively walks the directory tree, finds all .835/.edi/.txt files,
    skips duplicates (by content hash and already-imported filenames),
    validates that .txt files contain 835 data, and imports the rest.

    Returns a summary plus per-file details.
    """
    data = request.get_json(silent=True)
    if not data or 'folder_path' not in data:
        return jsonify({'error': 'Provide folder_path in JSON body'}), 400

    folder_path = data['folder_path']
    if not os.path.isdir(folder_path):
        return jsonify({'error': f'Folder not found: {folder_path}'}), 400

    results = parse_835_folder(folder_path, recursive=True)

    imported = [r for r in results if r.get('status') == 'imported']
    skipped = [r for r in results if r.get('status') == 'skipped']
    errors = [r for r in results if r.get('status') == 'error']
    dup_content = [r for r in skipped if r.get('reason') == 'duplicate content']
    dup_db = [r for r in skipped if r.get('reason') == 'already imported']
    dup_claims = [r for r in skipped if r.get('reason') == 'duplicate claims']
    not_835 = [r for r in skipped if r.get('reason') == 'not 835 content']

    total_claims = sum(r.get('claims_found', 0) for r in imported)
    total_claims_new = sum(r.get('claims_new', 0) for r in imported)
    total_claims_dup = sum(r.get('claims_duplicate', 0) for r in imported)
    # Also count duplicate claims from files that were fully skipped
    total_claims_dup += sum(r.get('claims_duplicate', 0) for r in dup_claims)
    total_payments = sum(r.get('payment_amount', 0) for r in imported)

    return jsonify({
        'folder': folder_path,
        'total_files_found': len(results),
        'files_imported': len(imported),
        'files_skipped': len(skipped),
        'files_errored': len(errors),
        'skip_reasons': {
            'duplicate_content': len(dup_content),
            'already_imported': len(dup_db),
            'duplicate_claims': len(dup_claims),
            'not_835_content': len(not_835),
        },
        'claims_found': total_claims,
        'claims_new': total_claims_new,
        'claims_duplicate': total_claims_dup,
        'payments_total': total_payments,
        'details': results,
    })


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
