"""Vendor connector API routes.

All operations are OUTBOUND-ONLY:
  - POST /api/vendor/credentials  — Store encrypted credentials locally
  - GET  /api/vendor/credentials  — List stored vendors (no secrets)
  - POST /api/vendor/download     — Download files from a vendor portal
"""
import os
from flask import request, jsonify, current_app
from app.vendor import vendor_bp
from app.vendor.credential_store import CredentialStore

CONNECTORS = {
    'officeally': 'app.vendor.office_ally.OfficeAllyConnector',
    'purview': 'app.vendor.purview.PurviewConnector',
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
        'IMPORT_FOLDER', os.path.join(os.getcwd(), 'import')
    )
    return cls(download_dir=os.path.join(download_dir, 'downloads'))


@vendor_bp.route('/credentials', methods=['POST'])
def store_credentials():
    """POST /api/vendor/credentials — Store vendor credentials (encrypted).

    Body: {vendor, username, password, master_password}
    """
    data = request.get_json()
    if not data:
        return jsonify({'error': 'JSON body required'}), 400

    required = ['vendor', 'username', 'password', 'master_password']
    missing = [f for f in required if f not in data]
    if missing:
        return jsonify({'error': f'Missing fields: {missing}'}), 400

    store = _get_store()
    try:
        store.unlock(data['master_password'])
        store.set(data['vendor'], data['username'], data['password'])
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


@vendor_bp.route('/download', methods=['POST'])
def vendor_download():
    """POST /api/vendor/download — Download files from a vendor portal.

    Body: {vendor, master_password, date_from?, date_to?, headless?}

    This is OUTBOUND-ONLY. Only your login credentials are sent to the
    vendor. No OCDR data leaves your machine.
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

    # Run download cycle
    result = connector.run(
        username=creds['username'],
        password=creds['password'],
        date_from=data.get('date_from'),
        date_to=data.get('date_to'),
    )

    return jsonify(result)


@vendor_bp.route('/connectors', methods=['GET'])
def list_connectors():
    """GET /api/vendor/connectors — List available vendor connectors."""
    return jsonify({
        'connectors': [
            {
                'name': 'officeally',
                'description': 'OfficeAlly — Download 835 ERA files',
                'requires': 'pip install playwright && playwright install chromium',
            },
            {
                'name': 'purview',
                'description': 'Purview PACS — Download reports and exports',
                'requires': 'pip install playwright && playwright install chromium',
            },
        ]
    })
