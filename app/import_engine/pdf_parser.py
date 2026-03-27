"""PDF and text-based EOB parser.

Extracts payment and claim data from:
  - PDF remittance/EOB documents (pdfplumber text extraction)
  - Plain text EOB files (vendor-specific formats)

Patterns detected:
  - Patient names (LAST, FIRST or FIRST LAST)
  - Service dates (MM/DD/YYYY, YYYY-MM-DD, M/D/YY)
  - Dollar amounts ($1,234.56 or 1234.56)
  - CPT codes (5-digit numeric)
  - Claim/reference numbers
  - Payer names
"""
import re
import os
from datetime import datetime, date

from app.models import db, EraPayment, EraClaimLine


# ---- Regex patterns for extracting payment data from unstructured text ----

# Dollar amounts: $1,234.56 or 1234.56 or -$500.00
_AMOUNT_RE = re.compile(r'-?\$?[\d,]+\.\d{2}')

# Dates: MM/DD/YYYY, M/D/YY, YYYY-MM-DD, MM-DD-YYYY
_DATE_RE = re.compile(
    r'\b(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2})\b'
)

# CPT codes: 5-digit numbers typically in 70000-99999 range (medical)
_CPT_RE = re.compile(r'\b([0-9]{5})\b')

# Patient name patterns: LAST, FIRST (comma required to avoid false positives
# like matching "BLUE CROSS" or "CHECK NUMBER" as patient names)
_NAME_RE = re.compile(r'\b([A-Z][A-Z\'-]{1,}),\s+([A-Z][A-Z\'-]{1,})\b')

# Check/EFT number patterns
# Handles "Check Number: CHK99887", "Check #CHK99887", "EFT: 12345"
_CHECK_RE = re.compile(
    r'(?:check\s*(?:number|num|no|#)?|ck|eft|trace|ref)[\s#:]+([A-Z0-9]{4,20})',
    re.IGNORECASE
)

# Claim number patterns
_CLAIM_RE = re.compile(
    r'(?:claim|clm|ref|icn|dcn)[\s#:]*([A-Z0-9]{6,20})', re.IGNORECASE
)

# Payer/insurance name (look for common payer identifiers)
_PAYER_KEYWORDS = [
    'BLUE CROSS', 'BLUE SHIELD', 'BCBS', 'AETNA', 'CIGNA', 'UNITED',
    'HUMANA', 'MEDICARE', 'MEDICAID', 'CALOPTIMA', 'ANTHEM', 'TRICARE',
    'WORKERS COMP', 'SELF PAY', 'ONE CALL',
]


def _parse_date_flexible(date_str):
    """Parse a date string in various formats."""
    for fmt in ('%m/%d/%Y', '%m/%d/%y', '%m-%d-%Y', '%Y-%m-%d', '%m/%d/%Y'):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _parse_amount_str(amount_str):
    """Parse a dollar amount string to float."""
    cleaned = amount_str.replace('$', '').replace(',', '').strip()
    try:
        return float(cleaned)
    except ValueError:
        return None


def _extract_payer(text):
    """Try to identify the payer/insurance company from text."""
    upper = text.upper()
    for kw in _PAYER_KEYWORDS:
        if kw in upper:
            return kw
    return None


def _extract_claims_from_text(text, filename='unknown'):
    """Extract claim-like records from unstructured text.

    Uses pattern matching to find patient names, dates, amounts, and CPT codes.
    Groups nearby matches into logical claim records.
    """
    lines = text.split('\n')
    claims = []
    payer = _extract_payer(text)
    check_match = _CHECK_RE.search(text)
    check_number = check_match.group(1) if check_match else None

    # Track payment totals for the header
    all_amounts = []
    payment_date = None

    # Process line by line, building claim records
    current_claim = None
    for line in lines:
        line_stripped = line.strip()
        if not line_stripped:
            # Empty line may separate claims
            if current_claim and current_claim.get('patient_name'):
                claims.append(current_claim)
                current_claim = None
            continue

        # Look for patient names
        name_match = _NAME_RE.search(line_stripped)
        dates = _DATE_RE.findall(line_stripped)
        amounts = _AMOUNT_RE.findall(line_stripped)
        cpts = _CPT_RE.findall(line_stripped)
        claim_ids = _CLAIM_RE.findall(line_stripped)

        # If we find a name, start a new claim
        if name_match:
            if current_claim and current_claim.get('patient_name'):
                claims.append(current_claim)
            current_claim = {
                'patient_name': f'{name_match.group(1)}, {name_match.group(2)}'.upper(),
                'service_date': None,
                'paid_amount': 0.0,
                'billed_amount': 0.0,
                'cpt_code': None,
                'claim_id': None,
            }

        if current_claim is None:
            current_claim = {
                'patient_name': None,
                'service_date': None,
                'paid_amount': 0.0,
                'billed_amount': 0.0,
                'cpt_code': None,
                'claim_id': None,
            }

        # Populate dates
        if dates and not current_claim.get('service_date'):
            d = _parse_date_flexible(dates[0])
            if d:
                current_claim['service_date'] = d
                if not payment_date:
                    payment_date = d

        # Populate amounts
        for amt_str in amounts:
            val = _parse_amount_str(amt_str)
            if val is not None:
                all_amounts.append(val)
                if current_claim['billed_amount'] == 0.0:
                    current_claim['billed_amount'] = val
                else:
                    current_claim['paid_amount'] = val

        # CPT codes
        if cpts and not current_claim.get('cpt_code'):
            # Filter for likely medical CPT codes (70000+)
            medical_cpts = [c for c in cpts if int(c) >= 70000]
            if medical_cpts:
                current_claim['cpt_code'] = medical_cpts[0]

        # Claim IDs
        if claim_ids and not current_claim.get('claim_id'):
            current_claim['claim_id'] = claim_ids[0]

    # Don't forget the last claim
    if current_claim and current_claim.get('patient_name'):
        claims.append(current_claim)

    # Compute total payment
    total_payment = sum(a for a in all_amounts if a > 0)

    return {
        'claims': claims,
        'payer': payer,
        'check_number': check_number,
        'payment_date': payment_date,
        'total_payment': total_payment,
    }


def parse_eob_pdf(filepath):
    """Parse an EOB/remittance PDF file.

    Uses pdfplumber to extract text, then applies pattern matching
    to find claim records.
    """
    import pdfplumber

    filename = os.path.basename(filepath)
    all_text = ''

    with pdfplumber.open(filepath) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                all_text += page_text + '\n'

            # Also try extracting tables
            tables = page.extract_tables()
            for table in tables:
                for row in table:
                    if row:
                        all_text += '\t'.join(str(cell) if cell else '' for cell in row) + '\n'

    if not all_text.strip():
        return {
            'claims_found': 0,
            'needs_ocr': True,
            'message': 'No selectable text in PDF — requires OCR processing',
        }

    return _store_extracted_claims(all_text, filename, source='PDF_EOB')


def parse_eob_text(filepath):
    """Parse a plain-text EOB file (non-835 vendor format)."""
    filename = os.path.basename(filepath)
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        text = f.read()
    return _store_extracted_claims(text, filename, source='TEXT_EOB')


def _store_extracted_claims(text, filename, source='PDF_EOB'):
    """Extract claims from text and store in the database."""
    extracted = _extract_claims_from_text(text, filename)
    claims = extracted['claims']

    if not claims:
        return {
            'claims_found': 0,
            'claims_new': 0,
            'claims_duplicate': 0,
            'message': 'No claim records could be extracted from file',
        }

    # Create an EraPayment header for this document
    era_payment = EraPayment(
        filename=filename,
        check_eft_number=extracted.get('check_number'),
        payment_amount=extracted.get('total_payment', 0.0),
        payment_date=extracted.get('payment_date'),
        payment_method=source,
        payer_name=extracted.get('payer'),
    )
    db.session.add(era_payment)
    db.session.flush()

    claims_new = 0
    claims_duplicate = 0

    for claim in claims:
        # Check for existing duplicate
        q = EraClaimLine.query
        if claim.get('claim_id'):
            q = q.filter_by(claim_id=claim['claim_id'])
        if claim.get('patient_name'):
            q = q.filter_by(patient_name_835=claim['patient_name'])
        if claim.get('service_date'):
            q = q.filter_by(service_date_835=claim['service_date'])
        q = q.filter_by(paid_amount=claim.get('paid_amount', 0.0))

        if q.first() is not None:
            claims_duplicate += 1
            continue

        claim_line = EraClaimLine(
            era_payment_id=era_payment.id,
            claim_id=claim.get('claim_id'),
            claim_status='1',  # Default to processed
            billed_amount=claim.get('billed_amount', 0.0),
            paid_amount=claim.get('paid_amount', 0.0),
            patient_name_835=claim.get('patient_name'),
            service_date_835=claim.get('service_date'),
            cpt_code=claim.get('cpt_code'),
        )
        db.session.add(claim_line)
        claims_new += 1

    # Remove empty payment header if all claims were duplicates
    if claims_new == 0 and claims_duplicate > 0:
        db.session.delete(era_payment)

    db.session.commit()

    return {
        'claims_found': len(claims),
        'claims_new': claims_new,
        'claims_duplicate': claims_duplicate,
        'payer_detected': extracted.get('payer'),
        'payment_amount': extracted.get('total_payment', 0.0),
        'source': source,
    }
