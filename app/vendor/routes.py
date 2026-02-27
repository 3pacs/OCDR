"""Vendor connector API routes.

All operations are OUTBOUND-ONLY:
  - POST /api/vendor/credentials      — Store encrypted credentials locally
  - GET  /api/vendor/credentials       — List stored vendors (no secrets)
  - DELETE /api/vendor/credentials/<v> — Remove vendor credentials
  - POST /api/vendor/download          — Download files from a vendor portal
  - POST /api/vendor/sync/start        — Start background sync
  - POST /api/vendor/sync/stop         — Stop background sync
  - GET  /api/vendor/sync/status       — Get sync status
  - POST /api/vendor/sync/<vendor>     — Sync a single vendor now
  - GET  /api/vendor/connectors        — List available connectors
"""
import os
from flask import request, jsonify, current_app
from app.vendor import vendor_bp
from app.vendor.credential_store import CredentialStore

CONNECTORS = {
    'candelis': 'app.vendor.candelis.CandelisConnector',
    'purview': 'app.vendor.purview.PurviewConnector',
    'officeally': 'app.vendor.office_ally.OfficeAllyConnector',
}

VENDOR_INFO = {
    'candelis': {
        'name': 'candelis',
        'display_name': 'Candelis RadSuite',
        'description': 'RIS — Billing records, schedule, and patient data',
        'icon': 'bi-hospital',
        'default_url': 'http://10.254.111.108',
        'requires': 'pip install playwright && playwright install chromium',
        'data_types': ['billing', 'schedule'],
    },
    'purview': {
        'name': 'purview',
        'display_name': 'Purview PACS',
        'description': 'PACS — Study list, reports, and imaging metadata',
        'icon': 'bi-image',
        'default_url': 'https://image-us-east1.purview.net/login',
        'requires': 'pip install playwright && playwright install chromium',
        'data_types': ['studies', 'reports'],
    },
    'officeally': {
        'name': 'officeally',
        'display_name': 'OfficeAlly',
        'description': 'Download 835 ERA remittance files',
        'icon': 'bi-file-earmark-medical',
        'default_url': 'https://pm.officeally.com/pm/login.aspx',
        'requires': 'pip install playwright && playwright install chromium',
        'data_types': ['era'],
    },
}


def _get_store():
    """Get or create credential store instance."""
    path = os.path.join(os.getcwd(), '.credentials.enc')
    return CredentialStore(path)


def _get_connector(vendor_name):
    """Import and instantiate a vendor connector by name."""
    if vendor_name not in CONNECTORS:
        return None
    module_path, class_name = CONNECTORS[vendor_name].rsplit('.', 1)
    import importlib
    module = importlib.import_module(module_path)
    cls = getattr(module, class_name)
    download_dir = current_app.config.get(
        'UPLOAD_FOLDER', os.path.join(os.getcwd(), 'uploads')
    )
    return cls(download_dir=os.path.join(download_dir, 'import'))


# ── Credential Management ────────────────────────────────────────

@vendor_bp.route('/credentials', methods=['POST'])
def store_credentials():
    """POST /api/vendor/credentials — Store vendor credentials (encrypted).

    Body: {vendor, username, password, master_password, portal_url?}
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    required = ['vendor', 'username', 'password', 'master_password']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({'error': f'Missing fields: {missing}'}), 400

    vendor_name = data['vendor']
    if vendor_name not in CONNECTORS:
        return jsonify({
            'error': f'Unknown vendor: {vendor_name}',
            'available': list(CONNECTORS.keys()),
        }), 400

    store = _get_store()
    try:
        store.unlock(data['master_password'])

        # Store portal_url in extra if provided
        extra = {}
        if data.get('portal_url'):
            extra['portal_url'] = data['portal_url']

        store.set(
            data['vendor'],
            data['username'],
            data['password'],
            extra=extra if extra else None,
        )
        store.save()
    except Exception as e:
        return jsonify({'error': f'Failed to store credentials: {e}'}), 500

    return jsonify({
        'stored': True,
        'vendor': data['vendor'],
        'username': data['username'],
    })


@vendor_bp.route('/credentials', methods=['GET'])
def list_credentials():
    """GET /api/vendor/credentials — List stored vendors (no secrets shown).

    Query: ?master_password=...
    """
    master = request.args.get('master_password')
    if not master:
        return jsonify({'error': 'master_password query param required'}), 400

    store = _get_store()
    try:
        store.unlock(master)
        vendors = store.list_vendors()
    except Exception as e:
        return jsonify({'error': f'Failed to unlock store: {e}'}), 500

    return jsonify({'vendors': vendors})


@vendor_bp.route('/credentials/<vendor_name>', methods=['DELETE'])
def delete_credentials(vendor_name):
    """DELETE /api/vendor/credentials/<vendor> — Remove stored credentials."""
    data = request.get_json()
    if not data or 'master_password' not in data:
        return jsonify({'error': 'master_password required'}), 400

    store = _get_store()
    try:
        store.unlock(data['master_password'])
        store.delete(vendor_name)
        store.save()
    except Exception as e:
        return jsonify({'error': str(e)}), 500

    return jsonify({'deleted': True, 'vendor': vendor_name})


# ── Manual Download ───────────────────────────────────────────────

@vendor_bp.route('/download', methods=['POST'])
def vendor_download():
    """POST /api/vendor/download — Download files from a vendor portal.

    Body: {vendor, master_password, date_from?, date_to?, headless?}
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    vendor_name = data.get('vendor')
    master_password = data.get('master_password')

    if not vendor_name or not master_password:
        return jsonify({'error': 'vendor and master_password required'}), 400

    # Get credentials
    store = _get_store()
    try:
        store.unlock(master_password)
        creds = store.get(vendor_name)
    except Exception as e:
        return jsonify({'error': f'Failed to unlock credentials: {e}'}), 500

    if not creds:
        return jsonify({'error': f'No credentials stored for {vendor_name}'}), 404

    # Get connector
    connector = _get_connector(vendor_name)
    if connector is None:
        return jsonify({
            'error': f'Unknown vendor: {vendor_name}',
            'available': list(CONNECTORS.keys()),
        }), 400

    # Set portal URL from stored extra if available
    extra = creds.get('extra', {}) or {}
    if extra.get('portal_url') and hasattr(connector, 'portal_url'):
        connector.portal_url = extra['portal_url']

    # Run download cycle
    result = connector.run(
        username=creds['username'],
        password=creds['password'],
        date_from=data.get('date_from'),
        date_to=data.get('date_to'),
    )

    return jsonify(result)


# ── Background Sync ──────────────────────────────────────────────

@vendor_bp.route('/sync/start', methods=['POST'])
def start_sync():
    """POST /api/vendor/sync/start — Start background data sync.

    Body: {master_password, interval?}
    Interval in seconds (default 300 = 5 minutes).
    """
    data = request.get_json()
    if not data or 'master_password' not in data:
        return jsonify({'error': 'master_password required'}), 400

    from app.vendor.sync_manager import start_sync as _start_sync

    interval = data.get('interval', 300)
    result = _start_sync(
        current_app._get_current_object(),
        interval=interval,
        master_key=data['master_password'],
    )

    return jsonify(result)


@vendor_bp.route('/sync/stop', methods=['POST'])
def stop_sync():
    """POST /api/vendor/sync/stop — Stop background data sync."""
    from app.vendor.sync_manager import stop_sync as _stop_sync
    result = _stop_sync()
    return jsonify(result)


@vendor_bp.route('/sync/status', methods=['GET'])
def sync_status():
    """GET /api/vendor/sync/status — Get background sync status."""
    from app.vendor.sync_manager import get_sync_status
    return jsonify(get_sync_status())


@vendor_bp.route('/sync/<vendor_name>', methods=['POST'])
def sync_vendor_now(vendor_name):
    """POST /api/vendor/sync/<vendor> — Sync a single vendor immediately.

    Body: {master_password}
    """
    data = request.get_json()
    if not data or 'master_password' not in data:
        return jsonify({'error': 'master_password required'}), 400

    from app.vendor.sync_manager import sync_vendor_once

    result = sync_vendor_once(
        vendor_name,
        current_app._get_current_object(),
        master_key=data['master_password'],
    )

    return jsonify(result)


# ── Connector Info ────────────────────────────────────────────────

@vendor_bp.route('/connectors', methods=['GET'])
def list_connectors():
    """GET /api/vendor/connectors — List available vendor connectors."""
    return jsonify({
        'connectors': list(VENDOR_INFO.values()),
    })
