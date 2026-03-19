"""F-05: Underpayment Detector (Sprint 16 — CPT-based rewrite)

Compares actual payment against expected rate from fee_schedule.
Primary lookup: CPT code + carrier (what insurers actually reimburse against).
Fallback: modality + carrier (legacy, for records without CPT codes).
Handles: gado/contrast premiums, PSMA, charge categories, per-carrier thresholds.
Single source of truth for expected rate lookups — used by all underpayment APIs.
"""
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from app.models import db, BillingRecord, FeeSchedule

underpayment_bp = Blueprint('underpayment', __name__)


# ── Payment method normalization ──────────────────────────────────

PAYMENT_METHOD_MAP = {
    # ERA 835 BPR codes -> normalized
    "CHK": "CHECK",
    "ACH": "EFT",
    "FWT": "WIRE",
    "NON": "NON_PAYMENT",
    # Common variations
    "CHECK": "CHECK",
    "EFT": "EFT",
    "WIRE": "WIRE",
    "CREDIT_CARD": "CREDIT_CARD",
    "CC": "CREDIT_CARD",
    "CASH": "CASH",
    "ELECTRONIC": "EFT",
}


def normalize_payment_method(raw_method):
    """Normalize payment method codes to standard values."""
    if not raw_method:
        return None
    return PAYMENT_METHOD_MAP.get(raw_method.upper().strip(), raw_method.upper().strip())


# ── Charge category inference ─────────────────────────────────────

def infer_charge_category(record):
    """Infer charge category from billing record fields.

    Returns: WITH_CONTRAST, WITHOUT_CONTRAST, PSMA, or STANDARD
    """
    if hasattr(record, 'charge_category') and record.charge_category:
        return record.charge_category

    if hasattr(record, 'is_psma') and record.is_psma and getattr(record, 'modality', '') == 'PET':
        return 'PSMA'

    if hasattr(record, 'gado_used') and record.gado_used:
        modality = getattr(record, 'modality', '')
        if modality in ('HMRI', 'OPEN', 'MR'):
            return 'WITH_CONTRAST'

    return 'STANDARD'


# ── Fee schedule loading ──────────────────────────────────────────

def build_fee_map():
    """Build a comprehensive fee lookup map from the fee_schedule table.

    Returns two dicts:
      cpt_map: keyed by (payer_code, cpt_code) -> {expected_rate, threshold, sample_count}
      modality_map: keyed by (payer_code, modality, charge_category) -> {expected_rate, threshold, gado_premium}

    Lookup priority:
      1. (carrier, cpt_code) -- CPT-level exact match
      2. (DEFAULT, cpt_code) -- CPT-level default
      3. (carrier, modality, category) -- modality-level carrier match
      4. (carrier, modality, STANDARD) -- modality-level without category
      5. (DEFAULT, modality, STANDARD) -- global modality default
    """
    cpt_map = {}
    modality_map = {}

    for fs in FeeSchedule.query.all():
        cpt = getattr(fs, 'cpt_code', None)
        category = getattr(fs, 'charge_category', None) or 'STANDARD'
        sample_count = getattr(fs, 'sample_count', 0) or 0

        if cpt:
            # CPT-level entry
            key = (fs.payer_code, cpt)
            existing = cpt_map.get(key)
            # Prefer entry with more samples
            if not existing or sample_count > existing.get('sample_count', 0):
                cpt_map[key] = {
                    'expected_rate': fs.expected_rate,
                    'threshold': fs.underpayment_threshold or 0.80,
                    'sample_count': sample_count,
                    'modality': fs.modality,
                }
        else:
            # Modality-level entry (legacy)
            key = (fs.payer_code, fs.modality, category)
            modality_map[key] = {
                'expected_rate': fs.expected_rate,
                'threshold': fs.underpayment_threshold or 0.80,
                'gado_premium': fs.gado_premium or 0.0,
            }
            # Also store as STANDARD for fallback
            base_key = (fs.payer_code, fs.modality, 'STANDARD')
            if base_key not in modality_map:
                modality_map[base_key] = modality_map[key]

    return {'cpt': cpt_map, 'modality': modality_map}


def get_expected_rate_from_map(fee_map, modality, carrier, charge_category='STANDARD', cpt_code=None):
    """Look up expected rate with CPT-first fallback chain.

    Returns (expected_rate, threshold, lookup_method) or (None, None, None).
    lookup_method is 'cpt' or 'modality' for debugging.
    """
    cpt_map = fee_map['cpt']
    mod_map = fee_map['modality']

    # ── CPT-based lookup (preferred) ──────────────────────────────
    if cpt_code:
        # 1a. Exact: carrier + CPT
        entry = cpt_map.get((carrier, cpt_code))
        if entry and entry['sample_count'] >= 3:
            return entry['expected_rate'], entry['threshold'], 'cpt'

        # 1b. Default CPT rate
        entry = cpt_map.get(('DEFAULT', cpt_code))
        if entry and entry['sample_count'] >= 3:
            return entry['expected_rate'], entry['threshold'], 'cpt'

        # 1c. Try with low sample count if no modality fallback exists
        entry = cpt_map.get((carrier, cpt_code)) or cpt_map.get(('DEFAULT', cpt_code))
        if entry:
            # Use CPT rate even with few samples, but only if we also don't
            # have a good modality match (checked below)
            cpt_rate = entry['expected_rate']
            cpt_threshold = entry['threshold']
        else:
            cpt_rate = None
            cpt_threshold = None
    else:
        cpt_rate = None
        cpt_threshold = None

    # ── Modality-based lookup (fallback) ──────────────────────────
    # 2. Exact match: carrier + modality + category
    entry = mod_map.get((carrier, modality, charge_category))

    # 3. Carrier + modality (STANDARD category)
    if not entry and charge_category != 'STANDARD':
        entry = mod_map.get((carrier, modality, 'STANDARD'))

    # 4. PSMA default
    if not entry and charge_category == 'PSMA' and modality == 'PET':
        entry = mod_map.get(('DEFAULT_PSMA', 'PET', 'PSMA'))
        if not entry:
            entry = mod_map.get(('DEFAULT_PSMA', 'PET', 'STANDARD'))

    # 5. Global default for modality
    if not entry:
        entry = mod_map.get(('DEFAULT', modality, charge_category))
    if not entry:
        entry = mod_map.get(('DEFAULT', modality, 'STANDARD'))

    if entry:
        expected = entry['expected_rate']
        threshold = entry['threshold']

        # Apply gado premium for contrast studies
        if charge_category == 'WITH_CONTRAST':
            gado_premium = entry.get('gado_premium', 0.0)
            if gado_premium > 0:
                expected += gado_premium
            else:
                expected += 200.0

        # If we had a CPT rate, use whichever is higher (more specific = CPT)
        if cpt_rate is not None:
            return cpt_rate, cpt_threshold, 'cpt'
        return expected, threshold, 'modality'

    # No modality match either — use CPT rate if we had one
    if cpt_rate is not None:
        return cpt_rate, cpt_threshold, 'cpt'

    return None, None, None


def get_expected_rate(modality, carrier, gado_used=False, is_psma=False,
                     charge_category=None, cpt_code=None):
    """Single-record expected rate lookup (convenience wrapper).

    Builds fee map each call -- for batch operations use build_fee_map() +
    get_expected_rate_from_map() directly.
    """
    if charge_category is None:
        if is_psma and modality == 'PET':
            charge_category = 'PSMA'
        elif gado_used and modality in ('HMRI', 'OPEN', 'MR'):
            charge_category = 'WITH_CONTRAST'
        else:
            charge_category = 'STANDARD'

    fee_map = build_fee_map()
    expected, threshold, method = get_expected_rate_from_map(
        fee_map, modality, carrier, charge_category, cpt_code
    )
    return expected, threshold


# ── Actual payment for comparison ─────────────────────────────────

def get_actual_payment(record):
    """Get the best available actual payment amount for a billing record.

    Priority: era_paid_amount (from matched 835) > total_payment (from billing import)
    """
    if hasattr(record, 'era_paid_amount') and record.era_paid_amount is not None:
        return record.era_paid_amount
    return record.total_payment or 0.0


# ── Underpayment check (per record) ──────────────────────────────

def check_underpayment(record, fee_map=None):
    """Check if a single billing record is underpaid.

    Returns dict with underpayment details, or None if not underpaid.
    """
    if fee_map is None:
        fee_map = build_fee_map()

    actual = get_actual_payment(record)
    if actual <= 0:
        return None  # unpaid -- not an underpayment, it's a denial

    charge_cat = infer_charge_category(record)
    cpt = getattr(record, 'cpt_code', None)

    expected, threshold, method = get_expected_rate_from_map(
        fee_map, record.modality, record.insurance_carrier, charge_cat, cpt
    )
    if expected is None or expected <= 0:
        return None

    if actual < (expected * threshold):
        variance = actual - expected
        return {
            'expected_rate': round(expected, 2),
            'variance': round(variance, 2),
            'pct_of_expected': round(actual / expected * 100, 1) if expected else 0,
            'charge_category': charge_cat,
            'threshold_used': threshold,
            'actual_payment': round(actual, 2),
            'cpt_code': cpt,
            'lookup_method': method,
        }
    return None


# ── CPT Fee Schedule Builder ─────────────────────────────────────

def build_cpt_fee_schedule_from_era():
    """Analyze ERA payment history and build/update CPT-level fee schedule entries.

    Groups ERA claim line payments by (carrier, CPT code) and computes
    median expected rate. Only creates entries with >= 3 samples for reliability.

    Returns count of entries created/updated.
    """
    from sqlalchemy import text

    # Get payment stats by CPT + carrier (using payer_name from era_payments)
    rows = db.session.execute(text('''
        SELECT
            ep.payer_name,
            ecl.cpt_code,
            COUNT(*) as cnt,
            AVG(ecl.paid_amount) as avg_paid,
            MIN(ecl.paid_amount) as min_paid,
            MAX(ecl.paid_amount) as max_paid
        FROM era_claim_lines ecl
        JOIN era_payments ep ON ecl.era_payment_id = ep.id
        WHERE ecl.cpt_code IS NOT NULL AND ecl.cpt_code != ''
          AND ecl.paid_amount > 0
        GROUP BY ep.payer_name, ecl.cpt_code
        HAVING COUNT(*) >= 3
        ORDER BY cnt DESC
    ''')).fetchall()

    # Map ERA payer names to our carrier codes
    from app.models import Payer
    carrier_map = _build_carrier_map()

    count = 0
    for row in rows:
        payer_name, cpt, cnt, avg_paid, min_paid, max_paid = row
        carrier = carrier_map.get(payer_name, payer_name)

        # Determine modality from CPT code
        modality = _cpt_to_modality(cpt)

        # Use avg as expected rate (could use median with more data)
        expected = round(avg_paid, 2)

        # Check if entry exists
        existing = FeeSchedule.query.filter_by(
            payer_code=carrier,
            cpt_code=cpt,
        ).first()

        if existing:
            existing.expected_rate = expected
            existing.sample_count = cnt
            existing.source = 'ERA_DERIVED'
            if modality:
                existing.modality = modality
        else:
            fs = FeeSchedule(
                payer_code=carrier,
                modality=modality or 'UNKNOWN',
                cpt_code=cpt,
                expected_rate=expected,
                underpayment_threshold=0.80,
                source='ERA_DERIVED',
                sample_count=cnt,
            )
            db.session.add(fs)
        count += 1

    # Also build DEFAULT rates by CPT (across all carriers)
    default_rows = db.session.execute(text('''
        SELECT
            ecl.cpt_code,
            COUNT(*) as cnt,
            AVG(ecl.paid_amount) as avg_paid
        FROM era_claim_lines ecl
        WHERE ecl.cpt_code IS NOT NULL AND ecl.cpt_code != ''
          AND ecl.paid_amount > 0
        GROUP BY ecl.cpt_code
        HAVING COUNT(*) >= 5
    ''')).fetchall()

    for row in default_rows:
        cpt, cnt, avg_paid = row
        modality = _cpt_to_modality(cpt)
        expected = round(avg_paid, 2)

        existing = FeeSchedule.query.filter_by(
            payer_code='DEFAULT',
            cpt_code=cpt,
        ).first()

        if existing:
            existing.expected_rate = expected
            existing.sample_count = cnt
            existing.source = 'ERA_DERIVED'
        else:
            fs = FeeSchedule(
                payer_code='DEFAULT',
                modality=modality or 'UNKNOWN',
                cpt_code=cpt,
                expected_rate=expected,
                underpayment_threshold=0.80,
                source='ERA_DERIVED',
                sample_count=cnt,
            )
            db.session.add(fs)
        count += 1

    if count > 0:
        db.session.commit()

    return count


def _build_carrier_map():
    """Map ERA payer names to our normalized carrier codes.

    Builds from both hardcoded known mappings and the Payer table.
    """
    # Known ERA payer name -> billing carrier code
    known = {
        'MEDICARE SERVICE CENTER': 'M/M',
        'MEDICARE': 'M/M',
        'NORIDIAN HEALTHCARE SOLUTIONS, LLC': 'M/M',
        'CALOPTIMA': 'CALOPTIMA',
        'CA MEDI-CAL': 'CALOPTIMA',
        'BLUE SHIELD OF CALIFORNIA PROMISE HEALTH PLAN': 'CALOPTIMA',
        'CALPERS': 'INS',
        'ANTHEM BC LIFE   HEALTH INS CO': 'INS',
        'ANTHEM BC LIFE & HEALTH INS CO': 'INS',
        'ANTHEM INSURANCE COMPANIES, INC.': 'INS',
        'BLUE CROSS OF CALIFORNIA (CA)': 'INS',
        'CALIFORNIA PHYSICIANS SERVICE DBA BLUE SHIELD CA': 'INS',
        'CIGNA HEALTH AND LIFE INSURANCE COMPANY': 'INS',
        'PROSPECT MEDICAL SYSTEMS': 'FAMILY',
        'UNITED CARE MEDICAL GROUP': 'FAMILY',
        'FEP BASIC CLAIMS ACCOUNT-FACETS': 'INS',
        'FEP PPO BLUE FOCUS CLAIMS ACCOUNT': 'INS',
        'FEP STANDARD CLAIMS ACCOUNT-FACETS': 'INS',
        'POSTAL SERVICE HBP-BASIC': 'INS',
        'POSTAL SERVICE HBP-STD': 'INS',
    }
    return known


# CPT code prefix -> modality mapping
_CPT_MODALITY = {
    # CT
    '700': 'CT', '701': 'CT', '702': 'CT', '703': 'CT', '704': 'CT',
    '712': 'CT', '713': 'CT', '741': 'CT', '742': 'CT',
    # MRI
    '705': 'HMRI', '706': 'HMRI', '707': 'HMRI',
    '721': 'HMRI', '722': 'HMRI', '723': 'HMRI', '737': 'HMRI',
    # PET
    '788': 'PET', '783': 'PET',
    # Nuclear medicine / BONE
    '782': 'BONE', '780': 'BONE',
    # DX / X-ray
    '710': 'DX', '711': 'DX', '730': 'DX', '731': 'DX',
    # Contrast agents (not a modality)
    'A95': None, 'Q99': None,
}


def _cpt_to_modality(cpt_code):
    """Infer modality from CPT code prefix."""
    if not cpt_code:
        return None
    # Handle multi-CPT strings like "78815, A9552"
    primary = cpt_code.split(',')[0].strip()
    for prefix_len in (3,):
        prefix = primary[:prefix_len]
        if prefix in _CPT_MODALITY:
            return _CPT_MODALITY[prefix]
    return None


# ── API Routes ────────────────────────────────────────────────────

@underpayment_bp.route('/underpayments', methods=['GET'])
def list_underpayments():
    """GET /api/underpayments - List underpaid claims"""
    carrier_filter = request.args.get('carrier')
    modality_filter = request.args.get('modality')
    cpt_filter = request.args.get('cpt_code')
    custom_threshold = request.args.get('threshold', type=float)
    page = request.args.get('page', 1, type=int)
    per_page = min(max(1, request.args.get('per_page', 50, type=int)), 500)

    query = BillingRecord.query.filter(BillingRecord.total_payment > 0)
    if carrier_filter:
        query = query.filter(BillingRecord.insurance_carrier == carrier_filter)
    if modality_filter:
        query = query.filter(BillingRecord.modality == modality_filter)
    if cpt_filter:
        query = query.filter(BillingRecord.cpt_code == cpt_filter)

    query = query.order_by(BillingRecord.total_payment.asc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    fee_map = build_fee_map()
    results = []

    for record in pagination.items:
        underpay = check_underpayment(record, fee_map)
        if underpay is None:
            continue

        if custom_threshold is not None:
            actual = get_actual_payment(record)
            if actual >= underpay['expected_rate'] * custom_threshold:
                continue

        results.append({
            **record.to_dict(),
            **underpay,
        })

    return jsonify({
        'underpayments': results,
        'total': len(results),
        'page': page,
    })


@underpayment_bp.route('/underpayments/summary', methods=['GET'])
def underpayment_summary():
    """GET /api/underpayments/summary - Aggregate underpayment stats"""
    fee_map = build_fee_map()
    paid_records = BillingRecord.query.filter(
        BillingRecord.total_payment > 0
    ).yield_per(500)

    total_flagged = 0
    total_variance = 0.0
    by_carrier = {}
    by_modality = {}
    by_charge_category = {}
    by_cpt = {}
    by_lookup_method = {'cpt': 0, 'modality': 0}

    for record in paid_records:
        underpay = check_underpayment(record, fee_map)
        if underpay is None:
            continue

        total_flagged += 1
        variance = underpay['variance']
        total_variance += variance
        charge_cat = underpay['charge_category']
        method = underpay.get('lookup_method', 'modality')
        by_lookup_method[method] = by_lookup_method.get(method, 0) + 1

        # By carrier
        c = record.insurance_carrier
        if c not in by_carrier:
            by_carrier[c] = {'count': 0, 'variance': 0.0}
        by_carrier[c]['count'] += 1
        by_carrier[c]['variance'] += variance

        # By modality
        m = record.modality
        if m not in by_modality:
            by_modality[m] = {'count': 0, 'variance': 0.0}
        by_modality[m]['count'] += 1
        by_modality[m]['variance'] += variance

        # By charge category
        if charge_cat not in by_charge_category:
            by_charge_category[charge_cat] = {'count': 0, 'variance': 0.0}
        by_charge_category[charge_cat]['count'] += 1
        by_charge_category[charge_cat]['variance'] += variance

        # By CPT code
        cpt = underpay.get('cpt_code')
        if cpt:
            if cpt not in by_cpt:
                by_cpt[cpt] = {'count': 0, 'variance': 0.0}
            by_cpt[cpt]['count'] += 1
            by_cpt[cpt]['variance'] += variance

    # Round variances
    for v in by_carrier.values():
        v['variance'] = round(v['variance'], 2)
    for v in by_modality.values():
        v['variance'] = round(v['variance'], 2)
    for v in by_charge_category.values():
        v['variance'] = round(v['variance'], 2)
    for v in by_cpt.values():
        v['variance'] = round(v['variance'], 2)

    return jsonify({
        'total_flagged': total_flagged,
        'total_variance': round(total_variance, 2),
        'lookup_methods': by_lookup_method,
        'by_carrier': [{'carrier': k, **v} for k, v in sorted(by_carrier.items(), key=lambda x: x[1]['variance'])],
        'by_modality': [{'modality': k, **v} for k, v in sorted(by_modality.items(), key=lambda x: x[1]['variance'])],
        'by_charge_category': [{'category': k, **v} for k, v in sorted(by_charge_category.items(), key=lambda x: x[1]['variance'])],
        'by_cpt': [{'cpt_code': k, **v} for k, v in sorted(by_cpt.items(), key=lambda x: x[1]['variance'])[:20]],
    })


@underpayment_bp.route('/underpayments/rebuild-cpt-fees', methods=['POST'])
def rebuild_cpt_fees():
    """POST /api/underpayments/rebuild-cpt-fees - Rebuild CPT-based fee schedule from ERA data"""
    count = build_cpt_fee_schedule_from_era()
    return jsonify({
        'status': 'ok',
        'entries_created_or_updated': count,
    })
