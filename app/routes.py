"""
Frontend page routes.
"""

from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required
from werkzeug.security import generate_password_hash, check_password_hash

from app import db
from app.models import User, Patient, Document

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    """Dashboard / landing page."""
    total_patients = Patient.query.count()
    total_docs = Document.query.count()
    pending_docs = Document.query.filter(
        Document.status.in_(["uploaded", "parsed"])
    ).count()
    matched_docs = Document.query.filter_by(status="matched").count()
    filed_docs = Document.query.filter_by(status="filed").count()

    recent_docs = Document.query.order_by(
        Document.created_at.desc()
    ).limit(10).all()

    return render_template(
        "index.html",
        total_patients=total_patients,
        total_docs=total_docs,
        pending_docs=pending_docs,
        matched_docs=matched_docs,
        filed_docs=filed_docs,
        recent_docs=recent_docs,
    )


@main_bp.route("/scan")
def scan_page():
    """Document scanner page."""
    return render_template("scan.html")


@main_bp.route("/documents")
def documents_page():
    """Document queue / inbox."""
    status = request.args.get("status", "")
    query = Document.query
    if status:
        query = query.filter_by(status=status)
    docs = query.order_by(Document.created_at.desc()).all()
    return render_template("documents.html", documents=docs, current_status=status)


@main_bp.route("/documents/<int:doc_id>")
def document_detail(doc_id):
    """Document detail / review page."""
    doc = db.session.get(Document, doc_id)
    if not doc:
        flash("Document not found", "danger")
        return redirect(url_for("main.documents_page"))
    patients = Patient.query.order_by(Patient.last_name, Patient.first_name).all()
    return render_template("document_detail.html", document=doc, patients=patients)


@main_bp.route("/patients")
def patients_page():
    """Patient list."""
    search = request.args.get("search", "").strip()
    query = Patient.query
    if search:
        s = f"%{search.upper()}%"
        query = query.filter(
            db.or_(
                Patient.last_name.ilike(s),
                Patient.first_name.ilike(s),
            )
        )
    patients = query.order_by(Patient.last_name, Patient.first_name).all()
    return render_template("patients.html", patients=patients, search=search)


@main_bp.route("/patients/<int:patient_id>")
def patient_detail(patient_id):
    """Patient file view with photo and documents."""
    patient = db.session.get(Patient, patient_id)
    if not patient:
        flash("Patient not found", "danger")
        return redirect(url_for("main.patients_page"))
    documents = patient.documents.all()
    return render_template("patient_detail.html", patient=patient, documents=documents)


@main_bp.route("/patients/new")
def new_patient():
    """New patient form."""
    return render_template("patient_form.html", patient=None)


@main_bp.route("/patients/<int:patient_id>/edit")
def edit_patient(patient_id):
    """Edit patient form."""
    patient = db.session.get(Patient, patient_id)
    if not patient:
        flash("Patient not found", "danger")
        return redirect(url_for("main.patients_page"))
    return render_template("patient_form.html", patient=patient)


# ---------------------------------------------------------------------------
# Auth (simple local auth)
# ---------------------------------------------------------------------------

@main_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for("main.index"))
        flash("Invalid credentials", "danger")
    return render_template("login.html")


@main_bp.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("main.index"))


@main_bp.route("/setup", methods=["GET", "POST"])
def setup():
    """First-time setup: create admin user."""
    if User.query.count() > 0:
        return redirect(url_for("main.index"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        if username and password:
            user = User(
                username=username,
                password_hash=generate_password_hash(password),
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Admin account created!", "success")
            return redirect(url_for("main.index"))
        flash("Username and password required", "danger")

    return render_template("setup.html")
