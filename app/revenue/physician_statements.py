"""Physician Statement Reconciliation (F-10).

Auto-generates monthly statements for reading physicians.
Tracks OWED vs PAID. Supports PDF export.
"""

from datetime import date, datetime
from io import BytesIO

from app.models import db, BillingRecord, PhysicianStatement


def generate_statement(physician_name, year, month):
    """Generate a monthly statement for a reading physician.

    Finds all billing_records where reading_physician matches,
    within the given year/month period.

    Returns:
        dict with statement details and line items
    """
    period = f"{year}-{month:02d}"
    start_date = date(year, month, 1)
    if month == 12:
        end_date = date(year + 1, 1, 1)
    else:
        end_date = date(year, month + 1, 1)

    # Escape LIKE wildcards in user input
    escaped = physician_name.replace("%", r"\%").replace("_", r"\_")

    # Search by reading_physician first
    records = BillingRecord.query.filter(
        BillingRecord.reading_physician.ilike(f"%{escaped}%"),
        BillingRecord.service_date >= start_date,
        BillingRecord.service_date < end_date,
    ).order_by(BillingRecord.service_date).all()

    # Also check referring_doctor
    referring_records = BillingRecord.query.filter(
        BillingRecord.referring_doctor.ilike(f"%{escaped}%"),
        BillingRecord.service_date >= start_date,
        BillingRecord.service_date < end_date,
    ).order_by(BillingRecord.service_date).all()

    all_records = {r.id: r for r in records}
    for r in referring_records:
        all_records[r.id] = r
    all_records = list(all_records.values())

    total_owed = sum(r.total_payment for r in all_records)

    # Upsert statement record
    stmt = PhysicianStatement.query.filter_by(
        physician_name=physician_name, statement_period=period
    ).first()

    if not stmt:
        stmt = PhysicianStatement(
            physician_name=physician_name,
            statement_period=period,
            total_owed=total_owed,
            total_paid=0.0,
            status="DRAFT",
        )
        db.session.add(stmt)
    else:
        stmt.total_owed = total_owed
    db.session.commit()

    line_items = [{
        "id": r.id,
        "patient_name": r.patient_name,
        "service_date": r.service_date.isoformat() if r.service_date else None,
        "scan_type": r.scan_type,
        "modality": r.modality,
        "total_payment": r.total_payment,
        "insurance_carrier": r.insurance_carrier,
    } for r in all_records]

    return {
        "statement_id": stmt.id,
        "physician_name": physician_name,
        "period": period,
        "total_owed": round(total_owed, 2),
        "total_paid": round(stmt.total_paid, 2),
        "balance": round(total_owed - stmt.total_paid, 2),
        "status": stmt.status,
        "line_items": line_items,
        "line_count": len(line_items),
    }


def list_statements(physician=None, status=None, page=1, per_page=50):
    """List all physician statements with optional filters."""
    query = PhysicianStatement.query
    if physician:
        escaped = physician.replace("%", r"\%").replace("_", r"\_")
        query = query.filter(PhysicianStatement.physician_name.ilike(f"%{escaped}%"))
    if status:
        query = query.filter(PhysicianStatement.status == status.upper())

    results = query.order_by(PhysicianStatement.statement_period.desc()).paginate(
        page=page, per_page=per_page, error_out=False
    )

    return {
        "items": [{
            "id": s.id,
            "physician_name": s.physician_name,
            "period": s.statement_period,
            "total_owed": s.total_owed,
            "total_paid": s.total_paid,
            "balance": round((s.total_owed or 0) - (s.total_paid or 0), 2),
            "status": s.status,
        } for s in results.items],
        "total": results.total,
        "page": page,
        "pages": results.pages,
    }


def record_payment(statement_id, amount):
    """Record a payment against a statement."""
    stmt = db.session.get(PhysicianStatement, statement_id)
    if not stmt:
        return {"error": "Statement not found"}
    stmt.total_paid = (stmt.total_paid or 0) + amount
    if stmt.total_paid >= stmt.total_owed:
        stmt.status = "PAID"
    else:
        stmt.status = "PARTIAL"
    db.session.commit()
    return {
        "statement_id": statement_id,
        "total_paid": stmt.total_paid,
        "balance": round((stmt.total_owed or 0) - stmt.total_paid, 2),
        "status": stmt.status,
    }


def generate_statement_html(statement_data):
    """Generate simple HTML for a statement (for PDF rendering).

    All user-supplied values are HTML-escaped to prevent XSS.
    """
    from markupsafe import escape

    lines = statement_data.get("line_items", [])
    rows = ""
    for ln in lines:
        rows += f"""<tr>
            <td>{escape(str(ln['service_date'] or ''))}</td>
            <td>{escape(str(ln['patient_name'] or ''))}</td>
            <td>{escape(str(ln['scan_type'] or ''))}</td>
            <td>{escape(str(ln['modality'] or ''))}</td>
            <td>{escape(str(ln['insurance_carrier'] or ''))}</td>
            <td style="text-align:right">${ln['total_payment']:,.2f}</td>
        </tr>"""

    physician = escape(str(statement_data.get('physician_name', '')))
    period = escape(str(statement_data.get('period', '')))

    return f"""<!DOCTYPE html>
<html><head><style>
    body {{ font-family: Arial, sans-serif; margin: 40px; }}
    h1 {{ color: #1e293b; }}
    table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #1e293b; color: white; }}
    .totals {{ margin-top: 20px; font-size: 18px; }}
</style></head><body>
    <h1>Physician Statement</h1>
    <p><strong>Physician:</strong> {physician}</p>
    <p><strong>Period:</strong> {period}</p>
    <p><strong>Generated:</strong> {date.today().isoformat()}</p>
    <table>
        <thead><tr><th>Date</th><th>Patient</th><th>Scan</th><th>Modality</th><th>Insurance</th><th>Amount</th></tr></thead>
        <tbody>{rows}</tbody>
    </table>
    <div class="totals">
        <p><strong>Total Owed:</strong> ${statement_data['total_owed']:,.2f}</p>
        <p><strong>Total Paid:</strong> ${statement_data['total_paid']:,.2f}</p>
        <p><strong>Balance Due:</strong> ${statement_data['balance']:,.2f}</p>
    </div>
</body></html>"""
