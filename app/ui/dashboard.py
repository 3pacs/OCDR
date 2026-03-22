"""F-19: Dashboard and page routes.

Provides the main dashboard at / and all module pages.
"""
from flask import render_template
from app.ui import ui_bp


@ui_bp.route('/')
def index():
    """GET / - Main insights dashboard"""
    return render_template('dashboard.html')


@ui_bp.route('/import')
def import_page():
    """GET /import - File import dashboard"""
    return render_template('import_dashboard.html')


@ui_bp.route('/schedules')
def schedules_page():
    """GET /schedules - Dual calendar view (MRI + PET/CT)"""
    return render_template('schedule_calendar.html')


@ui_bp.route('/underpayments')
def underpayments_page():
    """GET /underpayments - Underpaid claims analysis"""
    return render_template('underpayments.html')


@ui_bp.route('/filing-deadlines')
def filing_deadlines_page():
    """GET /filing-deadlines - Timely filing deadline tracker"""
    return render_template('filing_deadlines.html')


@ui_bp.route('/denials')
def denials_page():
    """GET /denials - Denial appeal priority queue"""
    return render_template('denial_queue.html')


@ui_bp.route('/denials/<int:claim_id>')
def denial_detail_page(claim_id):
    """GET /denials/<id> - Denial detail with recoverability scoring"""
    from app.models import BillingRecord
    record = BillingRecord.query.get_or_404(claim_id)
    return render_template('denial_detail.html', claim=record.to_dict())


@ui_bp.route('/duplicates')
def duplicates_page():
    """GET /duplicates - Duplicate claim detection"""
    return render_template('duplicates.html')


@ui_bp.route('/secondary')
def secondary_page():
    """GET /secondary - Secondary insurance follow-up"""
    return render_template('secondary_queue.html')


@ui_bp.route('/written-off')
def written_off_page():
    """GET /written-off - Written-off claims management"""
    return render_template('written_off.html')
