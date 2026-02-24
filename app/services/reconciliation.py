"""
Reconciliation engine.

Matches Payment records (from OptumPay, Change Healthcare, OfficeAlly, etc.)
to BankTransaction rows (from imported bank statements).

Matching strategies (in priority order):
  1. Exact check number match
  2. Exact EFT trace number match
  3. Exact amount + date within ±3 days
  4. Fuzzy amount match (±$0.01) + date within ±7 days

Each unmatched payment or unmatched bank credit is flagged for manual review.
"""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Any


# ------------------------------------------------------------------ #
# Public API                                                          #
# ------------------------------------------------------------------ #

def run_auto_reconcile(statement_id: int | None = None) -> dict[str, Any]:
    """
    Run automatic reconciliation.
    If statement_id is given, only match transactions from that statement.
    Returns a summary dict.
    """
    from app.extensions import db
    from app.models.bank import BankTransaction, ReconciliationMatch
    from app.models.payment import Payment

    # Fetch unmatched payments
    unmatched_payments = db.session.execute(
        db.select(Payment).where(Payment.status == "unreconciled")
    ).scalars().all()

    # Fetch unmatched bank transactions (credits only — income matching)
    tx_query = db.select(BankTransaction).where(
        BankTransaction.reconciliation_status == "unmatched",
        BankTransaction.amount > 0,   # credits only
    )
    if statement_id:
        tx_query = tx_query.where(BankTransaction.statement_id == statement_id)
    unmatched_txns = db.session.execute(tx_query).scalars().all()

    matched = 0
    unmatched_p = 0

    for payment in unmatched_payments:
        result = _match_payment(payment, unmatched_txns)
        if result:
            bank_tx, confidence = result
            # Create the match record
            match = ReconciliationMatch(
                payment_id=payment.id,
                bank_transaction_id=bank_tx.id,
                match_type="auto",
                confidence=float(confidence),
                matched_by="system",
            )
            db.session.add(match)
            payment.status = "reconciled"
            bank_tx.reconciliation_status = "matched"
            # Remove from pool to avoid double-matching
            unmatched_txns = [t for t in unmatched_txns if t.id != bank_tx.id]
            matched += 1
        else:
            unmatched_p += 1

    db.session.commit()

    return {
        "matched": matched,
        "unmatched_payments": unmatched_p,
        "unmatched_bank_txns": len(unmatched_txns),
    }


def manual_match(payment_id: int, bank_transaction_id: int,
                 notes: str = "") -> dict[str, Any]:
    """Create a manual reconciliation match between a payment and a bank txn."""
    from app.extensions import db
    from app.models.bank import BankTransaction, ReconciliationMatch
    from app.models.payment import Payment

    payment = db.get_or_404(Payment, payment_id)
    bank_tx = db.get_or_404(BankTransaction, bank_transaction_id)

    # Remove any existing match
    if payment.reconciliation_match:
        db.session.delete(payment.reconciliation_match)
    if bank_tx.reconciliation_match:
        db.session.delete(bank_tx.reconciliation_match)

    match = ReconciliationMatch(
        payment_id=payment_id,
        bank_transaction_id=bank_transaction_id,
        match_type="manual",
        confidence=1.0,
        notes=notes,
        matched_by="user",
    )
    db.session.add(match)
    payment.status = "reconciled"
    bank_tx.reconciliation_status = "manual_match"
    db.session.commit()

    return {"success": True, "match_id": match.id}


def unmatch(match_id: int) -> dict[str, Any]:
    """Remove a reconciliation match and reset statuses."""
    from app.extensions import db
    from app.models.bank import ReconciliationMatch

    match = db.get_or_404(ReconciliationMatch, match_id)
    if match.payment:
        match.payment.status = "unreconciled"
    if match.bank_transaction:
        match.bank_transaction.reconciliation_status = "unmatched"
    db.session.delete(match)
    db.session.commit()
    return {"success": True}


def reconciliation_summary(statement_id: int | None = None) -> dict[str, Any]:
    """Return counts and totals for the reconciliation dashboard."""
    from app.extensions import db
    from app.models.bank import BankTransaction, BankStatement
    from app.models.payment import Payment

    p_total = db.session.execute(
        db.select(db.func.count(Payment.id))
    ).scalar() or 0
    p_reconciled = db.session.execute(
        db.select(db.func.count(Payment.id)).where(Payment.status == "reconciled")
    ).scalar() or 0
    p_unreconciled = p_total - p_reconciled

    tx_query_base = db.select(BankTransaction).where(BankTransaction.amount > 0)
    if statement_id:
        tx_query_base = tx_query_base.where(BankTransaction.statement_id == statement_id)

    all_credits = db.session.execute(tx_query_base).scalars().all()
    matched_credits = [t for t in all_credits if t.reconciliation_status != "unmatched"]

    return {
        "payments_total": p_total,
        "payments_reconciled": p_reconciled,
        "payments_unreconciled": p_unreconciled,
        "bank_credits_total": len(all_credits),
        "bank_credits_matched": len(matched_credits),
        "bank_credits_unmatched": len(all_credits) - len(matched_credits),
        "total_unreconciled_amount": float(
            sum(p.amount for p in db.session.execute(
                db.select(Payment).where(Payment.status == "unreconciled")
            ).scalars().all() or [])
        ),
    }


# ------------------------------------------------------------------ #
# Internal matching logic                                             #
# ------------------------------------------------------------------ #

def _match_payment(
    payment, bank_txns: list
) -> tuple | None:
    """
    Try to find the best matching bank transaction for a payment.
    Returns (bank_transaction, confidence) or None.
    """
    best_match = None
    best_confidence = 0.0

    p_amount = Decimal(str(payment.amount or 0))
    p_date = payment.payment_date
    p_check = (payment.check_number or "").strip()
    p_eft = (payment.eft_trace_number or "").strip()

    for tx in bank_txns:
        tx_amount = Decimal(str(tx.amount or 0))
        tx_date = tx.transaction_date
        tx_check = (tx.check_number or "").strip()

        confidence = 0.0

        # Strategy 1: exact check number
        if p_check and tx_check and p_check == tx_check:
            confidence = 1.0

        # Strategy 2: EFT trace in description
        elif p_eft and p_eft in (tx.description or ""):
            confidence = 0.95

        # Strategy 3: exact amount + close date
        elif p_amount == tx_amount and tx_amount > 0:
            if p_date and tx_date:
                day_diff = abs((p_date - tx_date).days)
                if day_diff <= 3:
                    confidence = 0.90
                elif day_diff <= 7:
                    confidence = 0.75
            else:
                confidence = 0.60

        # Strategy 4: near-exact amount (±$0.01) within 7 days
        elif abs(p_amount - tx_amount) <= Decimal("0.01") and tx_amount > 0:
            if p_date and tx_date and abs((p_date - tx_date).days) <= 7:
                confidence = 0.70

        if confidence > best_confidence:
            best_confidence = confidence
            best_match = tx

    # Require minimum 60% confidence for auto-match
    if best_match and best_confidence >= 0.60:
        return (best_match, best_confidence)
    return None
