"""F-19: Dashboard routes.

Provides the main dashboard at / and the import page at /import.
"""
from flask import render_template
from app.ui import ui_bp


@ui_bp.route('/')
def index():
    """GET / - Main dashboard"""
    return render_template('dashboard.html')


@ui_bp.route('/import')
def import_page():
    """GET /import - File import dashboard"""
    return render_template('import_dashboard.html')
