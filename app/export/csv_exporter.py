"""Excel CSV Export Bridge (F-18).

Exports billing_records to CSV matching the Excel Current sheet column order.
Supports scheduled export (every 15 min configurable).
"""

import csv
import os
from datetime import datetime, timedelta, timezone

from app.models import db, BillingRecord


# Excel column order (22 columns matching Current sheet)
EXPORT_COLUMNS = [
    ("Patient", lambda r: r.patient_name),
    ("Doctor", lambda r: r.referring_doctor),
    ("Scan", lambda r: r.scan_type),
    ("Gado", lambda r: "Y" if r.gado_used else ""),
    ("Insurance", lambda r: r.insurance_carrier),
    ("Type", lambda r: r.modality),
    ("Date", lambda r: r.service_date.strftime("%m/%d/%Y") if r.service_date else ""),
    ("Primary", lambda r: f"{r.primary_payment:.2f}" if r.primary_payment else "0.00"),
    ("Secondary", lambda r: f"{r.secondary_payment:.2f}" if r.secondary_payment else "0.00"),
    ("Total", lambda r: f"{r.total_payment:.2f}" if r.total_payment else "0.00"),
    ("Extra", lambda r: f"{r.extra_charges:.2f}" if r.extra_charges else "0.00"),
    ("ReadBy", lambda r: r.reading_physician or ""),
    ("ID", lambda r: str(r.patient_id) if r.patient_id else ""),
    ("Birth Date", lambda r: ""),  # Not tracked in current schema
    ("Patient Name", lambda r: r.patient_name),
    ("S Date", lambda r: _excel_serial_date(r.service_date) if r.service_date else ""),
    ("Modalities", lambda r: r.modality),
    ("Description", lambda r: r.description or ""),
    ("Month", lambda r: r.service_date.strftime("%B") if r.service_date else ""),
    ("Year", lambda r: str(r.service_date.year) if r.service_date else ""),
    ("New", lambda r: ""),
    ("Import Source", lambda r: r.import_source or ""),
]

EXCEL_EPOCH = datetime(1899, 12, 30)


def _excel_serial_date(d):
    """Convert a date to Excel serial date number."""
    if not d:
        return ""
    delta = datetime(d.year, d.month, d.day) - EXCEL_EPOCH
    return str(delta.days)


def export_billing_csv(output_path=None, app=None):
    """Export all billing records to CSV.

    Args:
        output_path: Full path for output CSV. If None, uses EXPORT_FOLDER/master_data.csv
        app: Flask app for config access

    Returns:
        dict: {filepath, record_count, file_size}
    """
    if output_path is None:
        if app:
            export_dir = app.config.get("EXPORT_FOLDER", "export")
        else:
            export_dir = "export"
        os.makedirs(export_dir, exist_ok=True)
        output_path = os.path.join(export_dir, "master_data.csv")

    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    records = BillingRecord.query.order_by(BillingRecord.service_date.desc()).yield_per(1000)

    record_count = 0
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        # Header row
        writer.writerow([col[0] for col in EXPORT_COLUMNS])
        # Data rows
        for r in records:
            writer.writerow([col[1](r) for col in EXPORT_COLUMNS])
            record_count += 1

    file_size = os.path.getsize(output_path)

    return {
        "filepath": output_path,
        "record_count": record_count,
        "file_size": file_size,
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }


def export_era_csv(output_path=None, app=None):
    """Export ERA claim lines to CSV."""
    from app.models import EraClaimLine

    if output_path is None:
        if app:
            export_dir = app.config.get("EXPORT_FOLDER", "export")
        else:
            export_dir = "export"
        os.makedirs(export_dir, exist_ok=True)
        output_path = os.path.join(export_dir, "era_claims.csv")

    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else ".", exist_ok=True)

    claims = EraClaimLine.query.order_by(EraClaimLine.id.desc()).yield_per(1000)

    record_count = 0
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["Claim ID", "Patient", "Service Date", "CPT", "Billed",
                         "Paid", "Status", "Group Code", "Reason Code", "Adjustment",
                         "Match Confidence", "Matched Billing ID"])
        for c in claims:
            writer.writerow([
                c.claim_id, c.patient_name_835,
                c.service_date_835.isoformat() if c.service_date_835 else "",
                c.cpt_code, c.billed_amount, c.paid_amount, c.claim_status,
                c.cas_group_code, c.cas_reason_code, c.cas_adjustment_amount,
                c.match_confidence, c.matched_billing_id,
            ])
            record_count += 1

    return {
        "filepath": output_path,
        "record_count": record_count,
        "file_size": os.path.getsize(output_path),
        "exported_at": datetime.now(timezone.utc).isoformat(),
    }
