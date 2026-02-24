from flask import Blueprint, render_template
from app.extensions import db
from app.models.vendor import Vendor
from app.models.purchase import Purchase

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    vendors = db.session.execute(
        db.select(Vendor).where(Vendor.active == True).order_by(Vendor.name)
    ).scalars().all()
    recent_purchases = db.session.execute(
        db.select(Purchase).order_by(Purchase.created_at.desc()).limit(10)
    ).scalars().all()
    return render_template("dashboard.html", vendors=vendors, recent_purchases=recent_purchases)


@main_bp.route("/vendors")
def vendors_page():
    vendors = db.session.execute(
        db.select(Vendor).order_by(Vendor.name)
    ).scalars().all()
    return render_template("vendors.html", vendors=vendors)


@main_bp.route("/imports")
def imports_page():
    return render_template("imports.html")


@main_bp.route("/connectors")
def connectors_page():
    return render_template("connectors.html")


@main_bp.route("/reconciliation")
def reconciliation_page():
    return render_template("reconciliation.html")
