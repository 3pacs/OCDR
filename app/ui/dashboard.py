import os
from flask import Blueprint, render_template
from app import db
from app.models import (
    BillingRecord, DevNote, CalendarConfig, CalendarEntry,
    CandelisConfig, CandelisStudy,
)

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
def index():
    cal_cfg = CalendarConfig.query.order_by(CalendarConfig.set_at.desc()).first()
    cal_entry_count = db.session.query(CalendarEntry).count()

    pdf_count = 0
    if cal_cfg and os.path.isdir(cal_cfg.pdf_folder_path):
        import glob
        pdf_count = len(glob.glob(
            os.path.join(cal_cfg.pdf_folder_path, '**', '*.pdf'), recursive=True
        ))

    # Candelis stats
    candelis_cfg = CandelisConfig.query.order_by(CandelisConfig.updated_at.desc()).first()
    candelis_studies = db.session.query(CandelisStudy).count()
    candelis_entries = db.session.query(CalendarEntry).filter_by(source_system='CANDELIS').count()
    candelis_matched = db.session.query(CalendarEntry).filter(
        CalendarEntry.source_system == 'CANDELIS',
        CalendarEntry.billing_record_id.isnot(None),
    ).count()

    stats = {
        'total_records': db.session.query(BillingRecord).count(),
        'open_notes': db.session.query(DevNote).filter_by(status='open').count(),
        'in_progress_notes': db.session.query(DevNote).filter_by(status='in_progress').count(),
        'resolved_notes': db.session.query(DevNote).filter_by(status='resolved').count(),
        'calendar_configured': cal_cfg is not None,
        'calendar_folder': cal_cfg.pdf_folder_path if cal_cfg else None,
        'calendar_pdfs': pdf_count,
        'calendar_entries': cal_entry_count,
        # Candelis
        'candelis_configured': candelis_cfg is not None,
        'candelis_server': candelis_cfg.server if candelis_cfg else None,
        'candelis_database': candelis_cfg.database if candelis_cfg else None,
        'candelis_last_sync': candelis_cfg.last_sync_at.isoformat() if candelis_cfg and candelis_cfg.last_sync_at else None,
        'candelis_last_status': candelis_cfg.last_sync_status if candelis_cfg else None,
        'candelis_studies': candelis_studies,
        'candelis_entries': candelis_entries,
        'candelis_matched': candelis_matched,
    }
    return render_template('dashboard.html', stats=stats)


@dashboard_bp.route('/health')
def health():
    return {
        'status': 'ok',
        'database': 'connected',
        'records': db.session.query(BillingRecord).count(),
    }
