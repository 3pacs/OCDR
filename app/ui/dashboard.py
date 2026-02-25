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


@ui_bp.route("/schedule")
def schedule_page():
    return render_template("schedule.html")


@ui_bp.route("/era-payments")
def era_payments_page():
    return render_template("era_payments.html")


@ui_bp.route("/match-review")
def match_review_page():
    return render_template("match_review.html")


@ui_bp.route("/denial-queue")
def denial_queue_page():
    return render_template("denial_queue.html")


@ui_bp.route("/psma")
def psma_page():
    return render_template("psma_dashboard.html")


@ui_bp.route("/gado")
def gado_page():
    return render_template("gado_dashboard.html")


@ui_bp.route("/denial-analytics")
def denial_analytics_page():
    return render_template("denial_analytics.html")


@ui_bp.route("/payment-reconciliation")
def payment_reconciliation_page():
    return render_template("payment_reconciliation.html")


@ui_bp.route("/statements")
def statements_page():
    return render_template("statements.html")


@ui_bp.route("/import")
def import_page():
    return render_template("import_data.html")


@ui_bp.route("/admin")
def admin_page():
    return render_template("admin.html")
