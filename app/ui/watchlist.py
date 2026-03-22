"""Watchlist API — track carriers, modalities, and custom tickers.

Users can add any "ticker" (carrier code, modality, or custom label)
to their watchlist. The API resolves live stats (claim count, revenue,
underpaid count, etc.) from the database for each ticker.
"""
from datetime import datetime

from flask import request, jsonify
from sqlalchemy import func

from app.ui import ui_bp
from app.models import db, BillingRecord, WatchlistItem
from app.revenue.underpayment_detector import get_expected_rate


@ui_bp.route('/api/watchlist', methods=['GET'])
def list_watchlist():
    """GET /api/watchlist - List all watchlist items with live stats."""
    items = WatchlistItem.query.order_by(
        WatchlistItem.sort_order.asc(),
        WatchlistItem.created_at.desc(),
    ).all()

    results = []
    for item in items:
        data = item.to_dict()
        data['live'] = _resolve_ticker_stats(item.ticker, item.category)
        results.append(data)

    return jsonify({'items': results, 'total': len(results)})


@ui_bp.route('/api/watchlist', methods=['POST'])
def add_watchlist_item():
    """POST /api/watchlist - Add a ticker to the watchlist.

    JSON body: { ticker, label?, category?, notes?, target_value?, alert_enabled? }
    """
    data = request.get_json(silent=True)
    if not data or 'ticker' not in data:
        return jsonify({'error': 'ticker is required'}), 400

    ticker = data['ticker'].strip().upper()

    # Auto-detect category if not provided
    category = data.get('category', '').upper()
    if not category:
        category = _detect_category(ticker)

    item = WatchlistItem(
        ticker=ticker,
        label=data.get('label', ticker),
        category=category,
        notes=data.get('notes'),
        target_value=data.get('target_value'),
        alert_enabled=data.get('alert_enabled', False),
        sort_order=data.get('sort_order', 0),
    )
    db.session.add(item)
    db.session.commit()

    result = item.to_dict()
    result['live'] = _resolve_ticker_stats(item.ticker, item.category)

    return jsonify(result), 201


@ui_bp.route('/api/watchlist/<int:item_id>', methods=['PUT'])
def update_watchlist_item(item_id):
    """PUT /api/watchlist/<id> - Update a watchlist item."""
    item = WatchlistItem.query.get(item_id)
    if not item:
        return jsonify({'error': 'Item not found'}), 404

    data = request.get_json(silent=True)
    if not data:
        return jsonify({'error': 'Provide JSON body'}), 400

    if 'ticker' in data:
        item.ticker = data['ticker'].strip().upper()
    if 'label' in data:
        item.label = data['label']
    if 'category' in data:
        item.category = data['category'].upper()
    if 'notes' in data:
        item.notes = data['notes']
    if 'target_value' in data:
        item.target_value = data['target_value']
    if 'alert_enabled' in data:
        item.alert_enabled = bool(data['alert_enabled'])
    if 'sort_order' in data:
        item.sort_order = data['sort_order']

    db.session.commit()

    result = item.to_dict()
    result['live'] = _resolve_ticker_stats(item.ticker, item.category)
    return jsonify(result)


@ui_bp.route('/api/watchlist/<int:item_id>', methods=['DELETE'])
def delete_watchlist_item(item_id):
    """DELETE /api/watchlist/<id> - Remove from watchlist."""
    item = WatchlistItem.query.get(item_id)
    if not item:
        return jsonify({'error': 'Item not found'}), 404

    db.session.delete(item)
    db.session.commit()
    return jsonify({'deleted': item_id})


@ui_bp.route('/api/watchlist/reorder', methods=['POST'])
def reorder_watchlist():
    """POST /api/watchlist/reorder - Update sort_order for all items.

    JSON body: { order: [id1, id2, id3, ...] }
    """
    data = request.get_json(silent=True)
    if not data or 'order' not in data:
        return jsonify({'error': 'Provide order array'}), 400

    for idx, item_id in enumerate(data['order']):
        item = WatchlistItem.query.get(item_id)
        if item:
            item.sort_order = idx

    db.session.commit()
    return jsonify({'reordered': len(data['order'])})


@ui_bp.route('/api/watchlist/suggestions', methods=['GET'])
def watchlist_suggestions():
    """GET /api/watchlist/suggestions - Suggest tickers based on DB data.

    Returns distinct carriers and modalities that exist in billing_records.
    """
    carriers = db.session.query(
        BillingRecord.insurance_carrier
    ).distinct().order_by(BillingRecord.insurance_carrier).all()

    modalities = db.session.query(
        BillingRecord.modality
    ).distinct().order_by(BillingRecord.modality).all()

    return jsonify({
        'carriers': [c[0] for c in carriers if c[0]],
        'modalities': [m[0] for m in modalities if m[0]],
    })


# ---- Live stat resolution ----

_KNOWN_MODALITIES = {'CT', 'HMRI', 'PET', 'BONE', 'OPEN', 'DX'}

_KNOWN_CARRIERS = None  # lazy-loaded


def _detect_category(ticker):
    """Auto-detect if a ticker is a carrier, modality, or general."""
    if ticker in _KNOWN_MODALITIES:
        return 'MODALITY'

    # Check if it's a known carrier from the DB
    carrier_count = BillingRecord.query.filter(
        BillingRecord.insurance_carrier == ticker
    ).limit(1).count()
    if carrier_count > 0:
        return 'CARRIER'

    return 'GENERAL'


def _resolve_ticker_stats(ticker, category):
    """Resolve live statistics for a ticker from billing_records.

    Returns dict with claim_count, revenue, avg_payment, underpaid_count,
    unpaid_count, and trend data.
    """
    stats = {
        'claim_count': 0,
        'revenue': 0.0,
        'avg_payment': 0.0,
        'unpaid_count': 0,
        'underpaid_count': 0,
    }

    if category == 'CARRIER':
        query = BillingRecord.query.filter(BillingRecord.insurance_carrier == ticker)
    elif category == 'MODALITY':
        query = BillingRecord.query.filter(BillingRecord.modality == ticker)
    else:
        # General: try carrier first, then modality, then skip
        carrier_count = BillingRecord.query.filter(
            BillingRecord.insurance_carrier == ticker
        ).count()
        if carrier_count > 0:
            query = BillingRecord.query.filter(BillingRecord.insurance_carrier == ticker)
        else:
            mod_count = BillingRecord.query.filter(
                BillingRecord.modality == ticker
            ).count()
            if mod_count > 0:
                query = BillingRecord.query.filter(BillingRecord.modality == ticker)
            else:
                return stats

    # Aggregate stats
    agg = db.session.query(
        func.count(BillingRecord.id),
        func.sum(BillingRecord.total_payment),
    ).filter(query.whereclause).first()

    if agg:
        stats['claim_count'] = agg[0] or 0
        stats['revenue'] = round(float(agg[1] or 0), 2)
        if stats['claim_count'] > 0:
            stats['avg_payment'] = round(stats['revenue'] / stats['claim_count'], 2)

    # Unpaid
    stats['unpaid_count'] = query.filter(BillingRecord.total_payment == 0).count()

    # Underpaid
    paid = query.filter(BillingRecord.total_payment > 0).all()
    underpaid = 0
    for r in paid:
        expected, threshold = get_expected_rate(
            r.modality, r.insurance_carrier, r.gado_used, r.is_psma
        )
        if expected and float(r.total_payment) < (float(expected) * float(threshold)):
            underpaid += 1
    stats['underpaid_count'] = underpaid

    return stats
