"""F-05: Underpayment Detector (Sprint 16 rewrite)

Compares actual payment against expected rate from fee_schedule.
Handles: gado/contrast premiums, PSMA, charge categories, per-carrier thresholds.
Single source of truth for expected rate lookups — used by all underpayment APIs.
"""
from flask import Blueprint, request, jsonify
from sqlalchemy import func
from app.models import db, BillingRecord, FeeSchedule

underpayment_bp = Blueprint('underpayment', __name__)


# ── Payment method normalization ──────────────────────────────────

PAYMENT_METHOD_MAP = {
    # ERA 835 BPR codes → normalized
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
        if modality in ('HMRI', 'OPEN'):
            return 'WITH_CONTRAST'

    return 'STANDARD'


# ── Fee schedule loading ──────────────────────────────────────────

def build_fee_map():
    """Build a comprehensive fee lookup map from the fee_schedule table.

    Returns dict keyed by (payer_code, modality, charge_category) with value
    (expected_rate, threshold, gado_premium). Falls back through:
      1. (carrier, modality, category) — exact match
      2. (carrier, modality, STANDARD) — carrier rate without category
      3. (DEFAULT_PSMA, PET, PSMA) — PSMA default
      4. (DEFAULT, modality, STANDARD) — global default
    """
    fee_map = {}
    for fs in FeeSchedule.query.all():
        category = getattr(fs, 'charge_category', None) or 'STANDARD'
        key = (fs.payer_code, fs.modality, category)
        fee_map[key] = {
            'expected_rate': fs.expected_rate,
            'threshold': fs.underpayment_threshold or 0.80,
            'gado_premium': fs.gado_premium or 0.0,
        }
        # Also store without category for backward compat lookup
        base_key = (fs.payer_code, fs.modality, 'STANDARD')
        if base_key not in fee_map:
            fee_map[base_key] = fee_map[key]
    return fee_map


def get_expected_rate_from_map(fee_map, modality, carrier, charge_category='STANDARD'):
    """Look up expected rate from pre-built fee map with fallback chain.

    Returns (expected_rate, threshold) or (None, None) if no rate found.
    """
    # 1. Exact match: carrier + modality + category
    entry = fee_map.get((carrier, modality, charge_category))

    # 2. Carrier + modality (STANDARD category)
    if not entry and charge_category != 'STANDARD':
        entry = fee_map.get((carrier, modality, 'STANDARD'))

    # 3. PSMA default
    if not entry and charge_category == 'PSMA' and modality == 'PET':
        entry = fee_map.get(('DEFAULT_PSMA', 'PET', 'PSMA'))
        if not entry:
            entry = fee_map.get(('DEFAULT_PSMA', 'PET', 'STANDARD'))

    # 4. Global default for modality
    if not entry:
        entry = fee_map.get(('DEFAULT', modality, charge_category))
    if not entry:
        entry = fee_map.get(('DEFAULT', modality, 'STANDARD'))

    if not entry:
        return None, None

    expected = entry['expected_rate']
    threshold = entry['threshold']

    # Apply gado premium for contrast studies
    if charge_category == 'WITH_CONTRAST':
        gado_premium = entry.get('gado_premium', 0.0)
        if gado_premium > 0:
            expected += gado_premium
        else:
            # Fallback: use hardcoded $200 if gado_premium not configured
            expected += 200.0

    return expected, threshold


def get_expected_rate(modality, carrier, gado_used=False, is_psma=False, charge_category=None):
    """Single-record expected rate lookup (convenience wrapper).

    Builds fee map each call — for batch operations use build_fee_map() +
    get_expected_rate_from_map() directly.
    """
    if charge_category is None:
        if is_psma and modality == 'PET':
            charge_category = 'PSMA'
        elif gado_used and modality in ('HMRI', 'OPEN'):
            charge_category = 'WITH_CONTRAST'
        else:
            charge_category = 'STANDARD'

    fee_map = build_fee_map()
    return get_expected_rate_from_map(fee_map, modality, carrier, charge_category)


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
        return None  # unpaid — not an underpayment, it's a denial

    charge_cat = infer_charge_category(record)
    expected, threshold = get_expected_rate_from_map(
        fee_map, record.modality, record.insurance_carrier, charge_cat
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
        }
    return None


# ── API Routes ────────────────────────────────────────────────────

@underpayment_bp.route('/underpayments', methods=['GET'])
def list_underpayments():
    """GET /api/underpayments - List underpaid claims"""
    carrier_filter = request.args.get('carrier')
    modality_filter = request.args.get('modality')
    custom_threshold = request.args.get('threshold', type=float)
    page = request.args.get('page', 1, type=int)
    per_page = min(max(1, request.args.get('per_page', 50, type=int)), 500)

    query = BillingRecord.query.filter(BillingRecord.total_payment > 0)
    if carrier_filter:
        query = query.filter(BillingRecord.insurance_carrier == carrier_filter)
    if modality_filter:
        query = query.filter(BillingRecord.modality == modality_filter)

    query = query.order_by(BillingRecord.total_payment.asc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    fee_map = build_fee_map()
    results = []

    for record in pagination.items:
        underpay = check_underpayment(record, fee_map)
        if underpay is None:
            continue

        if custom_threshold is not None:
            # Re-check with custom threshold
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

    for record in paid_records:
        underpay = check_underpayment(record, fee_map)
        if underpay is None:
            continue

        total_flagged += 1
        variance = underpay['variance']
        total_variance += variance
        charge_cat = underpay['charge_category']

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

    # Round variances
    for v in by_carrier.values():
        v['variance'] = round(v['variance'], 2)
    for v in by_modality.values():
        v['variance'] = round(v['variance'], 2)
    for v in by_charge_category.values():
        v['variance'] = round(v['variance'], 2)

    return jsonify({
        'total_flagged': total_flagged,
        'total_variance': round(total_variance, 2),
        'by_carrier': [{'carrier': k, **v} for k, v in sorted(by_carrier.items(), key=lambda x: x[1]['variance'])],
        'by_modality': [{'modality': k, **v} for k, v in sorted(by_modality.items(), key=lambda x: x[1]['variance'])],
        'by_charge_category': [{'category': k, **v} for k, v in sorted(by_charge_category.items(), key=lambda x: x[1]['variance'])],
    })
