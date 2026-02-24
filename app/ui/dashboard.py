"""UI routes for OCDR dashboard pages."""

from flask import Blueprint, render_template

ui_bp = Blueprint("ui", __name__)


@ui_bp.route("/")
def dashboard():
    return render_template("dashboard.html")


@ui_bp.route("/underpayments")
def underpayments_page():
    return render_template("underpayments.html")


@ui_bp.route("/denials")
def denials_page():
    return render_template("denials.html")


@ui_bp.route("/filing-deadlines")
def filing_deadlines_page():
    return render_template("filing_deadlines.html")


@ui_bp.route("/secondary")
def secondary_page():
    return render_template("secondary_queue.html")


@ui_bp.route("/payers")
def payers_page():
    return render_template("payer_dashboard.html")


@ui_bp.route("/physicians")
def physicians_page():
    return render_template("physician_dashboard.html")


@ui_bp.route("/duplicates")
def duplicates_page():
    return render_template("duplicates.html")
