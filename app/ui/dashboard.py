"""UI routes for OCDR dashboard pages."""

from flask import Blueprint, render_template, request, redirect, url_for, flash
from app.infra.auth import auth_required, admin_required

ui_bp = Blueprint("ui", __name__)


@ui_bp.route("/")
@auth_required
def dashboard():
    return render_template("dashboard.html")


@ui_bp.route("/underpayments")
@auth_required
def underpayments_page():
    return render_template("underpayments.html")


@ui_bp.route("/denials")
@auth_required
def denials_page():
    return render_template("denials.html")


@ui_bp.route("/filing-deadlines")
@auth_required
def filing_deadlines_page():
    return render_template("filing_deadlines.html")


@ui_bp.route("/secondary")
@auth_required
def secondary_page():
    return render_template("secondary_queue.html")


@ui_bp.route("/payers")
@auth_required
def payers_page():
    return render_template("payer_dashboard.html")


@ui_bp.route("/physicians")
@auth_required
def physicians_page():
    return render_template("physician_dashboard.html")


@ui_bp.route("/duplicates")
@auth_required
def duplicates_page():
    return render_template("duplicates.html")


@ui_bp.route("/schedule")
@auth_required
def schedule_page():
    return render_template("schedule.html")


@ui_bp.route("/schedules")
@auth_required
def schedule_calendar_page():
    return render_template("schedule_calendar.html")


@ui_bp.route("/era-payments")
@auth_required
def era_payments_page():
    return render_template("era_payments.html")


@ui_bp.route("/match-review")
@auth_required
def match_review_page():
    return render_template("match_review.html")


@ui_bp.route("/denial-queue")
@auth_required
def denial_queue_page():
    return render_template("denial_queue.html")


@ui_bp.route("/psma")
@auth_required
def psma_page():
    return render_template("psma_dashboard.html")


@ui_bp.route("/gado")
@auth_required
def gado_page():
    return render_template("gado_dashboard.html")


@ui_bp.route("/denial-analytics")
@auth_required
def denial_analytics_page():
    return render_template("denial_analytics.html")


@ui_bp.route("/payment-reconciliation")
@auth_required
def payment_reconciliation_page():
    return render_template("payment_reconciliation.html")


@ui_bp.route("/statements")
@auth_required
def statements_page():
    return render_template("statements.html")


@ui_bp.route("/import")
@auth_required
def import_page():
    return render_template("import_data.html")


@ui_bp.route("/vendor-connections")
@auth_required
def vendor_connections_page():
    return render_template("vendor_connections.html")


@ui_bp.route("/admin")
@admin_required
def admin_page():
    return render_template("admin.html")


@ui_bp.route("/smart-matching")
@auth_required
def smart_matching_page():
    return render_template("smart_matching.html")


@ui_bp.route("/chat")
@auth_required
def chat_page():
    return render_template("chat.html")


@ui_bp.route("/patients")
@auth_required
def patients_page():
    return render_template("patients.html")


@ui_bp.route("/aging")
@auth_required
def aging_page():
    return render_template("aging.html")


@ui_bp.route("/login", methods=["GET", "POST"])
def login():
    from flask_login import login_user, current_user
    from app.models import User

    if current_user.is_authenticated:
        return redirect(url_for("ui.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and user.check_password(password):
            from datetime import datetime, timezone
            user.last_login = datetime.now(timezone.utc)
            from app.models import db
            db.session.commit()
            login_user(user)
            next_page = request.args.get("next")
            return redirect(next_page or url_for("ui.dashboard"))
        flash("Invalid username or password", "error")
    return render_template("login.html")


@ui_bp.route("/logout")
def logout():
    from flask_login import logout_user
    logout_user()
    return redirect(url_for("ui.login"))
