"""F-19: Dashboard routes (Sprint 6 placeholder).

Provides the main dashboard at / and basic navigation.
"""
from flask import render_template
from app.ui import ui_bp


@ui_bp.route('/')
def index():
    """GET / - Main dashboard"""
    return render_template('dashboard.html')
