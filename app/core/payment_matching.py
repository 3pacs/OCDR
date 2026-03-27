"""Check/EFT Payment Matching (F-17).

Groups ERA claims by parent payment (check/EFT).
Imports bank statement CSVs to match deposits to checks.
Flags unmatched deposits and unmatched checks.
"""

import csv
import os
from datetime import datetime

from sqlalchemy import func

from app.models import db, EraPayment, EraClaimLine


def get_payment_summary():
    """Get payment reconciliation overview."""
    total_payments = EraPayment.query.count()
    total_amount = db.session.query(func.sum(EraPayment.payment_amount)).scalar() or 0

    by_method = db.session.query(
        EraPayment.payment_method,
        func.count(EraPayment.id).label("count"),
        func.sum(EraPayment.payment_amount).label("total"),
    ).group_by(EraPayment.payment_method).all()

    return {
        "total_payments": total_payments,
        "total_amount": round(total_amount, 2),
        "by_method": [{
            "method": r.payment_method,
            "count": r.count,
            "total": round(r.total or 0, 2),
        } for r in by_method],
    }


def get_payment_detail(check_number):
    """Get all claims under a specific check/EFT number."""
    payment = EraPayment.query.filter_by(check_eft_number=check_number).first()
    if not payment:
        return {"error": "Payment not found"}

    claims = EraClaimLine.query.filter_by(era_payment_id=payment.id).order_by(
        EraClaimLine.paid_amount.desc()
    ).all()

    return {
        "payment": payment.to_dict(),
        "claims": [c.to_dict() for c in claims],
        "claim_count": len(claims),
        "total_billed": round(sum(c.billed_amount or 0 for c in claims), 2),
        "total_paid": round(sum(c.paid_amount or 0 for c in claims), 2),
    }


def import_bank_statement(filepath):
    """Import a bank statement CSV and match against ERA payments.

    Expected CSV columns: date, amount, description
    Matches by:
      1. ERA payment amount ±$0.01 to bank deposit amount
      2. Check/EFT number found in bank description

    Returns reconciliation results.
    """
    result = {
        "matched": [],
        "unmatched_deposits": [],
        "unmatched_checks": [],
        "total_deposits": 0,
        "total_matched": 0,
    }

    deposits = []
    try:
        with open(filepath, "r", encoding="utf-8-sig", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Try common column names
                amount_str = row.get("amount") or row.get("Amount") or row.get("AMOUNT") or "0"
                date_str = row.get("date") or row.get("Date") or row.get("DATE") or ""
                desc = row.get("description") or row.get("Description") or row.get("DESCRIPTION") or ""

                try:
                    amount = abs(float(amount_str.replace(",", "").replace("$", "")))
                except (ValueError, TypeError):
                    continue

                deposit_date = None
                for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y"):
                    try:
                        deposit_date = datetime.strptime(date_str.strip(), fmt).date()
                        break
                    except ValueError:
                        continue

                deposits.append({
                    "amount": amount,
                    "date": deposit_date,
                    "description": desc,
                    "matched": False,
                })
    except Exception as e:
        result["error"] = str(e)
        return result

    result["total_deposits"] = len(deposits)

    # Get all ERA payments
    era_payments = EraPayment.query.all()
    era_matched = set()

    for deposit in deposits:
        best_match = None
        best_method = None

        for payment in era_payments:
            if payment.id in era_matched:
                continue

            # Method 1: Amount match (±$0.01)
            if payment.payment_amount and abs(payment.payment_amount - deposit["amount"]) <= 0.01:
                # Method 2: Check number in description
                if payment.check_eft_number and payment.check_eft_number in deposit["description"]:
                    best_match = payment
                    best_method = "amount+check"
                    break
                elif not best_match:
                    best_match = payment
                    best_method = "amount"

        if best_match:
            deposit["matched"] = True
            era_matched.add(best_match.id)
            result["matched"].append({
                "deposit_amount": deposit["amount"],
                "deposit_date": deposit["date"].isoformat() if deposit["date"] else None,
                "deposit_desc": deposit["description"],
                "era_payment_id": best_match.id,
                "era_check": best_match.check_eft_number,
                "era_amount": best_match.payment_amount,
                "era_payer": best_match.payer_name,
                "match_method": best_method,
            })
            result["total_matched"] += 1
        else:
            result["unmatched_deposits"].append({
                "amount": deposit["amount"],
                "date": deposit["date"].isoformat() if deposit["date"] else None,
                "description": deposit["description"],
            })

    # Find unmatched ERA payments
    for payment in era_payments:
        if payment.id not in era_matched:
            result["unmatched_checks"].append({
                "payment_id": payment.id,
                "check_number": payment.check_eft_number,
                "amount": payment.payment_amount,
                "payer": payment.payer_name,
                "date": payment.payment_date.isoformat() if payment.payment_date else None,
            })

    return result


def get_reconciliation_status():
    """Get overall reconciliation summary."""
    total_payments = EraPayment.query.count()

    # Payments with claims that have matched billing records
    matched_claims = EraClaimLine.query.filter(
        EraClaimLine.matched_billing_id.isnot(None)
    ).count()
    total_claims = EraClaimLine.query.count()

    return {
        "total_era_payments": total_payments,
        "total_claim_lines": total_claims,
        "matched_claims": matched_claims,
        "unmatched_claims": total_claims - matched_claims,
        "match_rate": round((matched_claims / total_claims * 100) if total_claims > 0 else 0, 1),
    }
