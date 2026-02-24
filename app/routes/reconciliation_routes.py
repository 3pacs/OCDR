from flask import Blueprint, jsonify, request, current_app
from app.extensions import db
from app.models.bank import BankStatement, BankTransaction, ReconciliationMatch
from app.models.payment import Payment
from app.services.bank_importer import import_bank_file, persist_statement
from app.services.reconciliation import (
    run_auto_reconcile,
    manual_match,
    unmatch,
    reconciliation_summary,
)

recon_bp = Blueprint("reconciliation", __name__)


# ------------------------------------------------------------------ #
# Bank statements                                                     #
# ------------------------------------------------------------------ #

@recon_bp.get("/statements")
def list_statements():
    stmts = db.session.execute(
        db.select(BankStatement).order_by(BankStatement.imported_at.desc())
    ).scalars().all()
    return jsonify([s.to_dict() for s in stmts])


@recon_bp.post("/statements/upload")
def upload_statement():
    """
    Upload a bank statement file (CSV, OFX, QFX).
    Form fields:
      file            - the file (required)
      account_name    - string (optional)
      account_last4   - last 4 of account number (optional)
    """
    if "file" not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files["file"]
    if not file.filename:
        return jsonify({"error": "Empty filename"}), 400

    account_name = request.form.get("account_name", "")
    account_last4 = request.form.get("account_last4", "")

    import tempfile, os
    ext = file.filename.rsplit(".", 1)[-1].lower()
    with tempfile.NamedTemporaryFile(delete=False, suffix=f".{ext}") as tmp:
        file.save(tmp.name)
        tmp_path = tmp.name

    try:
        result = import_bank_file(tmp_path, account_name, account_last4)
    finally:
        os.unlink(tmp_path)

    if not result.get("success"):
        return jsonify({"error": result.get("error", "Parse failed")}), 400

    stmt = persist_statement(
        result["statement"],
        result["transactions"],
        original_filename=file.filename,
    )

    return jsonify({
        "statement": stmt.to_dict(),
        "transactions_imported": result["count"],
    }), 201


@recon_bp.get("/statements/<int:stmt_id>/transactions")
def list_transactions(stmt_id: int):
    db.get_or_404(BankStatement, stmt_id)
    txns = db.session.execute(
        db.select(BankTransaction)
        .where(BankTransaction.statement_id == stmt_id)
        .order_by(BankTransaction.transaction_date)
    ).scalars().all()
    return jsonify([t.to_dict() for t in txns])


@recon_bp.delete("/statements/<int:stmt_id>")
def delete_statement(stmt_id: int):
    stmt = db.get_or_404(BankStatement, stmt_id)
    db.session.delete(stmt)
    db.session.commit()
    return jsonify({"message": "Statement deleted", "id": stmt_id})


# ------------------------------------------------------------------ #
# Reconciliation                                                      #
# ------------------------------------------------------------------ #

@recon_bp.post("/run")
def run_reconcile():
    """Auto-reconcile payments against bank transactions."""
    stmt_id = request.get_json(force=True).get("statement_id") if request.data else None
    summary = run_auto_reconcile(stmt_id)
    return jsonify(summary)


@recon_bp.post("/match")
def create_manual_match():
    """Manually match a payment to a bank transaction."""
    data = request.get_json(force=True)
    payment_id = data.get("payment_id")
    bank_tx_id = data.get("bank_transaction_id")
    notes = data.get("notes", "")

    if not payment_id or not bank_tx_id:
        return jsonify({"error": "payment_id and bank_transaction_id required"}), 400

    result = manual_match(payment_id, bank_tx_id, notes)
    return jsonify(result)


@recon_bp.delete("/match/<int:match_id>")
def delete_match(match_id: int):
    """Remove a reconciliation match."""
    result = unmatch(match_id)
    return jsonify(result)


@recon_bp.get("/summary")
def get_summary():
    """Reconciliation overview counts and totals."""
    stmt_id = request.args.get("statement_id", type=int)
    return jsonify(reconciliation_summary(stmt_id))


@recon_bp.get("/unmatched")
def get_unmatched():
    """Return all unmatched payments and unmatched bank credits."""
    unmatched_payments = db.session.execute(
        db.select(Payment).where(Payment.status == "unreconciled")
        .order_by(Payment.payment_date.desc())
    ).scalars().all()

    unmatched_txns = db.session.execute(
        db.select(BankTransaction).where(
            BankTransaction.reconciliation_status == "unmatched",
            BankTransaction.amount > 0,
        ).order_by(BankTransaction.transaction_date.desc())
    ).scalars().all()

    return jsonify({
        "unmatched_payments": [p.to_dict() for p in unmatched_payments],
        "unmatched_bank_transactions": [t.to_dict() for t in unmatched_txns],
    })


@recon_bp.get("/matches")
def list_matches():
    """Return all reconciliation matches with full detail."""
    matches = db.session.execute(
        db.select(ReconciliationMatch)
        .order_by(ReconciliationMatch.matched_at.desc())
    ).scalars().all()
    return jsonify([m.to_dict() for m in matches])


@recon_bp.put("/transactions/<int:tx_id>/ignore")
def ignore_transaction(tx_id: int):
    """Mark a bank transaction as intentionally ignored (fee, transfer, etc.)."""
    tx = db.get_or_404(BankTransaction, tx_id)
    tx.reconciliation_status = "ignored"
    db.session.commit()
    return jsonify(tx.to_dict())
