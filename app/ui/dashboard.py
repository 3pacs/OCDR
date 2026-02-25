from flask import Blueprint, render_template
from app import db
from app.models import BillingRecord, DevNote

dashboard_bp = Blueprint('dashboard', __name__)


@dashboard_bp.route('/')
def index():
    stats = {
        'total_records': db.session.query(BillingRecord).count(),
        'open_notes': db.session.query(DevNote).filter_by(status='open').count(),
        'in_progress_notes': db.session.query(DevNote).filter_by(status='in_progress').count(),
        'resolved_notes': db.session.query(DevNote).filter_by(status='resolved').count(),
    }
    return render_template('dashboard.html', stats=stats)


@dashboard_bp.route('/health')
def health():
    return {
        'status': 'ok',
        'database': 'connected',
        'records': db.session.query(BillingRecord).count(),
    }
