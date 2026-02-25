"""Candelis RIS integration API routes.

Endpoints:
  GET  /api/candelis/config       - Current connection settings (password masked)
  POST /api/candelis/config       - Save / update connection settings
  POST /api/candelis/test         - Test connectivity to Candelis DB
  POST /api/candelis/sync         - Trigger a data sync
  GET  /api/candelis/status       - Sync stats and last-sync info
  GET  /api/candelis/tables       - List available tables (for setup)
  GET  /api/candelis/columns      - List columns of a table (for setup)
"""

from datetime import datetime, timezone
from flask import Blueprint, jsonify, request
from app import db
from app.models import CandelisConfig, CandelisStudy, CalendarEntry

candelis_bp = Blueprint('candelis', __name__)


def _get_config():
    return CandelisConfig.query.order_by(CandelisConfig.updated_at.desc()).first()


def _mask_password(pw):
    if not pw:
        return ''
    if len(pw) <= 4:
        return '****'
    return pw[:2] + '*' * (len(pw) - 4) + pw[-2:]


# ── config ──────────────────────────────────────────────────────

@candelis_bp.route('/api/candelis/config', methods=['GET'])
def get_config():
    cfg = _get_config()
    if not cfg:
        return jsonify({'configured': False})
    return jsonify({
        'configured': True,
        'server': cfg.server,
        'database': cfg.database,
        'username': cfg.username,
        'password_masked': _mask_password(cfg.password),
        'port': cfg.port,
        'driver': cfg.driver,
        'study_table': cfg.study_table,
        'patient_table': cfg.patient_table,
        'auto_sync_enabled': cfg.auto_sync_enabled,
        'sync_interval_minutes': cfg.sync_interval_minutes,
        'last_sync_at': cfg.last_sync_at.isoformat() if cfg.last_sync_at else None,
        'last_sync_status': cfg.last_sync_status,
        'last_sync_message': cfg.last_sync_message,
        'last_sync_count': cfg.last_sync_count,
    })


@candelis_bp.route('/api/candelis/config', methods=['POST'])
def save_config():
    data = request.get_json(force=True)

    required = ['server', 'database', 'username', 'password']
    missing = [f for f in required if not data.get(f, '').strip()]
    if missing:
        return jsonify({'error': f"Missing required fields: {', '.join(missing)}"}), 400

    cfg = _get_config()
    if cfg:
        cfg.server = data['server'].strip()
        cfg.database = data['database'].strip()
        cfg.username = data['username'].strip()
        # Only update password if a real value was sent (not the masked placeholder)
        pw = data.get('password', '').strip()
        if pw and '****' not in pw:
            cfg.password = pw
        cfg.port = int(data.get('port', 1433))
        cfg.driver = data.get('driver', cfg.driver).strip()
        cfg.study_table = data.get('study_table', cfg.study_table).strip()
        cfg.patient_table = data.get('patient_table', cfg.patient_table).strip()
    else:
        cfg = CandelisConfig(
            server=data['server'].strip(),
            database=data['database'].strip(),
            username=data['username'].strip(),
            password=data['password'].strip(),
            port=int(data.get('port', 1433)),
            driver=data.get('driver', 'ODBC Driver 17 for SQL Server').strip(),
            study_table=data.get('study_table', 'Study').strip(),
            patient_table=data.get('patient_table', 'Patient').strip(),
        )
        db.session.add(cfg)

    db.session.commit()
    return jsonify({'ok': True, 'message': 'Configuration saved'}), 200


# ── test ────────────────────────────────────────────────────────

@candelis_bp.route('/api/candelis/test', methods=['POST'])
def test_connection():
    cfg = _get_config()
    if not cfg:
        return jsonify({'ok': False, 'message': 'No Candelis connection configured'}), 400

    from app.candelis.connector import CandelisConnector
    connector = CandelisConnector(cfg)
    ok, msg = connector.test_connection()

    # If connected, also grab study count
    count = None
    if ok:
        try:
            count = connector.fetch_study_count()
        except Exception:
            pass

    return jsonify({
        'ok': ok,
        'message': msg,
        'study_count': count,
    })


# ── sync ────────────────────────────────────────────────────────

@candelis_bp.route('/api/candelis/sync', methods=['POST'])
def sync():
    cfg = _get_config()
    if not cfg:
        return jsonify({'error': 'No Candelis connection configured'}), 400

    data = request.get_json(silent=True) or {}
    from_date = data.get('from_date')
    to_date = data.get('to_date')

    from app.candelis.connector import CandelisConnector
    from app.candelis.sync import run_sync

    connector = CandelisConnector(cfg)

    try:
        result = run_sync(connector, from_date=from_date, to_date=to_date)
        cfg.last_sync_at = datetime.now(timezone.utc)
        cfg.last_sync_status = 'success'
        cfg.last_sync_message = (
            f"Fetched {result['studies_fetched']} studies, "
            f"matched {result['billing_matched']} to billing"
        )
        cfg.last_sync_count = result['studies_fetched']
        db.session.commit()
        return jsonify({'ok': True, **result})
    except Exception as exc:
        cfg.last_sync_at = datetime.now(timezone.utc)
        cfg.last_sync_status = 'error'
        cfg.last_sync_message = str(exc)
        db.session.commit()
        return jsonify({'ok': False, 'error': str(exc)}), 500


# ── status ──────────────────────────────────────────────────────

@candelis_bp.route('/api/candelis/status', methods=['GET'])
def status():
    cfg = _get_config()
    study_count = db.session.query(CandelisStudy).count()
    candelis_entries = db.session.query(CalendarEntry).filter_by(
        source_system='CANDELIS'
    ).count()
    matched_entries = db.session.query(CalendarEntry).filter(
        CalendarEntry.source_system == 'CANDELIS',
        CalendarEntry.billing_record_id.isnot(None),
    ).count()

    return jsonify({
        'configured': cfg is not None,
        'last_sync_at': cfg.last_sync_at.isoformat() if cfg and cfg.last_sync_at else None,
        'last_sync_status': cfg.last_sync_status if cfg else None,
        'last_sync_message': cfg.last_sync_message if cfg else None,
        'last_sync_count': cfg.last_sync_count if cfg else 0,
        'total_studies': study_count,
        'calendar_entries': candelis_entries,
        'matched_entries': matched_entries,
        'unmatched_entries': candelis_entries - matched_entries,
    })


# ── schema discovery ────────────────────────────────────────────

@candelis_bp.route('/api/candelis/tables', methods=['GET'])
def list_tables():
    cfg = _get_config()
    if not cfg:
        return jsonify({'error': 'Not configured'}), 400

    from app.candelis.connector import CandelisConnector
    connector = CandelisConnector(cfg)
    try:
        tables = connector.list_tables()
        return jsonify({'tables': tables})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500


@candelis_bp.route('/api/candelis/columns', methods=['GET'])
def list_columns():
    cfg = _get_config()
    if not cfg:
        return jsonify({'error': 'Not configured'}), 400

    table = request.args.get('table', cfg.study_table)

    from app.candelis.connector import CandelisConnector
    connector = CandelisConnector(cfg)
    try:
        cols = connector.list_columns(table)
        return jsonify({'table': table, 'columns': cols})
    except Exception as exc:
        return jsonify({'error': str(exc)}), 500
