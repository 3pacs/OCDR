"""F-10: Physician / lane statements — unpaid-claims report → PDF.

Generates a clean statement of UNPAID claims for a billing lane / physician
(e.g. JHANGIANI, VU PHAN, BEACH), with the expected amount owed per claim
(from fee_schedule), for emailing.

Reusable two ways:
  - import get_unpaid_claims() / build_statement_pdf() from the API (a route)
  - run standalone:  python -m backend.app.revenue.physician_statements --lane JHANGIANI --out out.pdf
    (standalone connects via OCDR_PG_DSN env or the default host-exposed DSN)

Fail-closed: read-only query, no writes. PHI (patient names) appears in the
generated PDF by design (it's a billing doc) — keep PDFs local, never in the vault.
"""
from __future__ import annotations
import os
import argparse
from datetime import date

# ---- core query (psycopg2 sync; works standalone and in-container) ----
_DEFAULT_DSN = "postgresql://ocmri:ocmri_secret@localhost:5433/ocmri"


def get_unpaid_claims(lane: str, dsn: str | None = None) -> dict:
    """Return unpaid claims for a lane/carrier + expected-owed per claim.

    unpaid = total_payment = 0 AND not written off.
    expected owed = fee_schedule(payer=lane, modality) -> else fee_schedule(DEFAULT, modality) -> else 0.
    """
    import psycopg2
    import psycopg2.extras
    dsn = dsn or os.environ.get("OCDR_PG_DSN", _DEFAULT_DSN)
    conn = psycopg2.connect(dsn)
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT b.patient_name, b.patient_id, b.service_date, b.scan_type,
                   b.modality, b.description, b.referring_doctor,
                   COALESCE(b.billed_amount, 0)  AS billed_amount,
                   COALESCE(NULLIF(fl.expected_rate, 0), fd.expected_rate, 0) AS expected_owed
            FROM billing_records b
            -- fee_schedule has duplicate rows per (payer,modality); dedupe to one rate each
            LEFT JOIN (SELECT payer_code, modality, MAX(expected_rate) AS expected_rate
                       FROM fee_schedule GROUP BY payer_code, modality) fl
                   ON fl.payer_code = %(lane)s  AND fl.modality = b.modality
            LEFT JOIN (SELECT payer_code, modality, MAX(expected_rate) AS expected_rate
                       FROM fee_schedule GROUP BY payer_code, modality) fd
                   ON fd.payer_code = 'DEFAULT' AND fd.modality = b.modality
            WHERE b.insurance_carrier = %(lane)s
              AND COALESCE(b.total_payment, 0) = 0
              AND (b.denial_status IS NULL OR b.denial_status <> 'WRITTEN_OFF')
            ORDER BY b.service_date
            """,
            {"lane": lane},
        )
        rows = cur.fetchall()
    finally:
        conn.close()
    total_owed = round(sum(float(r["expected_owed"] or 0) for r in rows), 2)
    return {"lane": lane, "count": len(rows), "total_owed": total_owed, "claims": rows}


# ---- PDF render (reportlab) ----
def build_statement_pdf(data: dict, out_path: str) -> str:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import inch
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.platypus import (
        SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer,
    )

    styles = getSampleStyleSheet()
    doc = SimpleDocTemplate(out_path, pagesize=letter,
                            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
                            leftMargin=0.5 * inch, rightMargin=0.5 * inch)
    elems = []
    elems.append(Paragraph(f"Orange County Diagnostic Radiology", styles["Title"]))
    elems.append(Paragraph(f"Unpaid Claims — {data['lane']}", styles["Heading2"]))
    elems.append(Paragraph(f"As of {date.today():%B %d, %Y} &nbsp;|&nbsp; "
                           f"{data['count']} claims &nbsp;|&nbsp; "
                           f"Total owed: ${data['total_owed']:,.2f}", styles["Normal"]))
    elems.append(Spacer(1, 0.2 * inch))

    header = ["#", "Patient", "Chart", "DOS", "Scan", "Mod", "Owed $"]
    table_data = [header]
    for i, r in enumerate(data["claims"], 1):
        table_data.append([
            str(i),
            (r["patient_name"] or "")[:28],
            str(r["patient_id"] or ""),
            str(r["service_date"] or ""),
            (r["scan_type"] or "")[:16],
            (r["modality"] or "")[:6],
            f"{float(r['expected_owed'] or 0):,.2f}",
        ])
    table_data.append(["", "", "", "", "", "TOTAL", f"${data['total_owed']:,.2f}"])

    t = Table(table_data, repeatRows=1,
              colWidths=[0.3*inch, 2.0*inch, 0.7*inch, 0.9*inch, 1.4*inch, 0.6*inch, 0.9*inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f3a5f")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
        ("ALIGN", (-1, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "RIGHT"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#eef2f7")]),
        ("LINEBELOW", (0, -2), (-1, -2), 0.5, colors.grey),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
    ]))
    elems.append(t)
    doc.build(elems)
    return out_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lane", required=True, help="billing lane / insurance_carrier, e.g. JHANGIANI")
    ap.add_argument("--out", required=True, help="output PDF path")
    ap.add_argument("--dsn", default=None, help="postgres DSN (else OCDR_PG_DSN env / default)")
    args = ap.parse_args()
    data = get_unpaid_claims(args.lane, args.dsn)
    build_statement_pdf(data, args.out)
    print(f"{args.lane}: {data['count']} unpaid claims, total owed ${data['total_owed']:,.2f}")
    print(f"PDF -> {args.out}")


if __name__ == "__main__":
    main()
