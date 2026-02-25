import os
from flask import Blueprint, render_template
from app import db
from app.models import BillingRecord, DevNote, CalendarConfig, CalendarEntry

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

    stats = {
        'total_records': db.session.query(BillingRecord).count(),
        'open_notes': db.session.query(DevNote).filter_by(status='open').count(),
        'in_progress_notes': db.session.query(DevNote).filter_by(status='in_progress').count(),
        'resolved_notes': db.session.query(DevNote).filter_by(status='resolved').count(),
        'calendar_configured': cal_cfg is not None,
        'calendar_folder': cal_cfg.pdf_folder_path if cal_cfg else None,
        'calendar_pdfs': pdf_count,
        'calendar_entries': cal_entry_count,
    }
    return render_template('dashboard.html', stats=stats)


@dashboard_bp.route('/health')
def health():
    return {
        'status': 'ok',
        'database': 'connected',
        'records': db.session.query(BillingRecord).count(),
    }
