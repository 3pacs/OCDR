"""Background sync manager for vendor data import.

Runs as a daemon thread that periodically syncs data from Candelis and
Purview into OCDR's local database. Downloaded files are automatically
routed through the existing import engine (folder_watcher).

No patient data is ever sent out — only login credentials go to the
vendor portals. All data flows inbound.
"""
import os
import time
import threading
import logging
import collections
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_sync_thread = None
_sync_running = False
_sync_status = {
    'state': 'stopped',
    'vendors': {},
    'last_sync': None,
    'total_files_synced': 0,
    'total_records_imported': 0,
    'errors': collections.deque(maxlen=100),
    'current_vendor': None,
}


def _update_vendor_status(vendor, **kwargs):
    """Update the sync status for a specific vendor."""
    with _lock:
        if vendor not in _sync_status['vendors']:
            _sync_status['vendors'][vendor] = {
                'state': 'idle',
                'last_sync': None,
                'files_downloaded': 0,
                'records_imported': 0,
                'errors': [],
                'last_error': None,
            }
        _sync_status['vendors'][vendor].update(kwargs)


def _sync_vendor(vendor_name, app, creds, connector_cls, extra_kwargs=None):
    """Run a single sync cycle for one vendor.

    Downloads files from the vendor portal, then routes them through
    the existing folder_watcher import pipeline.
    """
    extra_kwargs = extra_kwargs or {}
    _update_vendor_status(vendor_name, state='syncing')

    with _lock:
        _sync_status['current_vendor'] = vendor_name

    download_dir = os.path.join(
        app.config.get('UPLOAD_FOLDER', 'uploads'), 'import'
    )
    os.makedirs(download_dir, exist_ok=True)

    # Create connector pointing downloads at the import folder
    # so folder_watcher will auto-process them
    connector = connector_cls(download_dir=download_dir, **extra_kwargs)

    try:
        logger.info(f'[sync] Starting sync for {vendor_name}...')

        result = connector.run(
            username=creds['username'],
            password=creds['password'],
            date_from=creds.get('extra', {}).get('date_from') if creds.get('extra') else None,
            date_to=creds.get('extra', {}).get('date_to') if creds.get('extra') else None,
        )

        files_downloaded = len(result.get('files', []))
        errors = result.get('errors', [])

        _update_vendor_status(
            vendor_name,
            state='idle',
            last_sync=datetime.now(timezone.utc).isoformat(),
            files_downloaded=files_downloaded,
            errors=errors[-5:] if errors else [],
            last_error=errors[-1] if errors else None,
        )

        with _lock:
            _sync_status['total_files_synced'] += files_downloaded
            for err in errors:
                _sync_status['errors'].append(f'[{vendor_name}] {err}')

        if files_downloaded > 0:
            logger.info(
                f'[sync] {vendor_name}: downloaded {files_downloaded} files. '
                f'Folder watcher will auto-import them.'
            )
            # Trigger a manual scan of the import folder so files are
            # processed immediately rather than waiting for next poll
            _trigger_import_scan(app)
        else:
            logger.info(f'[sync] {vendor_name}: no new files found.')

        if errors:
            logger.warning(f'[sync] {vendor_name}: {len(errors)} errors: {errors}')

        return result

    except Exception as e:
        error_msg = f'{vendor_name} sync error: {e}'
        logger.error(f'[sync] {error_msg}')
        _update_vendor_status(
            vendor_name,
            state='error',
            last_error=str(e),
        )
        with _lock:
            _sync_status['errors'].append(error_msg)
        return {'vendor': vendor_name, 'files': [], 'errors': [str(e)]}

    finally:
        with _lock:
            _sync_status['current_vendor'] = None


def _trigger_import_scan(app):
    """Trigger the folder watcher to scan for new files immediately."""
    try:
        from app.monitor.folder_watcher import scan_once
        scan_once(app)
    except Exception as e:
        logger.warning(f'[sync] Could not trigger import scan: {e}')


def _get_configured_vendors(app):
    """Get list of vendors that have stored credentials.

    Returns list of (vendor_name, creds_dict, connector_class, extra_kwargs).
    """
    from app.vendor.credential_store import CredentialStore

    cred_path = os.path.join(os.getcwd(), '.credentials.enc')
    if not os.path.exists(cred_path):
        return []

    store = CredentialStore(cred_path)

    # Try to unlock with stored master key (set during initial config)
    master_key = app.config.get('VENDOR_MASTER_KEY')
    if not master_key:
        # Check environment
        master_key = os.environ.get('VENDOR_MASTER_KEY')
    if not master_key:
        logger.debug('[sync] No master key available for credential store')
        return []

    try:
        store.unlock(master_key)
    except Exception as e:
        logger.error(f'[sync] Failed to unlock credential store: {e}')
        return []

    vendors = []

    # Check for Candelis credentials
    candelis_creds = store.get('candelis')
    if candelis_creds:
        from app.vendor.candelis import CandelisConnector
        extra = candelis_creds.get('extra', {}) or {}
        portal_url = extra.get('portal_url', 'http://10.254.111.108')
        vendors.append((
            'candelis',
            candelis_creds,
            CandelisConnector,
            {'portal_url': portal_url, 'headless': True},
        ))

    # Check for Purview credentials
    purview_creds = store.get('purview')
    if purview_creds:
        from app.vendor.purview import PurviewConnector
        extra = purview_creds.get('extra', {}) or {}
        portal_url = extra.get('portal_url', 'https://image-us-east1.purview.net/login')
        vendors.append((
            'purview',
            purview_creds,
            PurviewConnector,
            {'portal_url': portal_url, 'headless': True},
        ))

    return vendors


def _sync_loop(app, interval=300):
    """Main sync loop. Runs all configured vendor syncs at regular intervals.

    Default interval: 5 minutes (300 seconds).
    """
    global _sync_running

    with _lock:
        _sync_status['state'] = 'running'

    logger.info(f'[sync] Background sync started (interval={interval}s)')

    # First run: sync immediately
    _run_all_syncs(app)

    while True:
        with _lock:
            if not _sync_running:
                break

        # Sleep in short increments so we can stop quickly
        for _ in range(interval):
            with _lock:
                if not _sync_running:
                    break
            time.sleep(1)

        with _lock:
            if not _sync_running:
                break

        _run_all_syncs(app)

    with _lock:
        _sync_status['state'] = 'stopped'

    logger.info('[sync] Background sync stopped.')


def _run_all_syncs(app):
    """Run sync for all configured vendors."""
    with _lock:
        _sync_status['last_sync'] = datetime.now(timezone.utc).isoformat()

    vendors = _get_configured_vendors(app)
    if not vendors:
        logger.info('[sync] No vendors configured. Skipping sync cycle.')
        return

    for vendor_name, creds, connector_cls, extra_kwargs in vendors:
        with _lock:
            if not _sync_running:
                break
        _sync_vendor(vendor_name, app, creds, connector_cls, extra_kwargs)


def start_sync(app, interval=300, master_key=None):
    """Start the background sync in a daemon thread.

    Args:
        app: Flask application instance
        interval: Seconds between sync cycles (default 5 minutes)
        master_key: Master password for the credential store.
                    If provided, stored in app.config for the sync thread.
    """
    global _sync_thread, _sync_running

    if master_key:
        app.config['VENDOR_MASTER_KEY'] = master_key

    with _lock:
        if _sync_running:
            return {'status': 'already_running'}
        _sync_running = True

    _sync_thread = threading.Thread(
        target=_sync_loop,
        args=(app, interval),
        daemon=True,
    )
    _sync_thread.start()

    return {
        'status': 'started',
        'interval': interval,
    }


def stop_sync():
    """Stop the background sync."""
    global _sync_running
    with _lock:
        _sync_running = False
    return {'status': 'stopping'}


def get_sync_status():
    """Get current sync status."""
    with _lock:
        status = dict(_sync_status)
        status['errors'] = list(status['errors'])
        status['vendors'] = dict(status['vendors'])
    return status


def sync_vendor_once(vendor_name, app, master_key=None):
    """Run a single sync for a specific vendor (non-background).

    Used for manual "Sync Now" button clicks.
    """
    if master_key:
        app.config['VENDOR_MASTER_KEY'] = master_key

    vendors = _get_configured_vendors(app)
    for v_name, creds, connector_cls, extra_kwargs in vendors:
        if v_name == vendor_name:
            return _sync_vendor(vendor_name, app, creds, connector_cls, extra_kwargs)

    return {
        'vendor': vendor_name,
        'files': [],
        'errors': [f'Vendor {vendor_name} not configured or credentials missing'],
    }
