"""
Bank statement importer.

Supports:
  - CSV  (standard bank exports — column auto-detection)
  - OFX  (Open Financial Exchange — .ofx files)
  - QFX  (Quicken Financial Exchange — .qfx files, same format as OFX)
  - Manual entry via JSON payload

Returns normalised BankStatement + BankTransaction rows.
"""
from __future__ import annotations

import csv
import io
import os
from datetime import date, datetime
from decimal import Decimal
from typing import Any


# ------------------------------------------------------------------ #
# Main entry points                                                   #
# ------------------------------------------------------------------ #

def import_bank_file(filepath: str, account_name: str = "",
                     account_last4: str = "") -> dict[str, Any]:
    """
    Detect file format, parse, return dict ready for DB insertion.
    """
    ext = filepath.rsplit(".", 1)[-1].lower()

    if ext in ("ofx", "qfx"):
        return _parse_ofx(filepath, account_name, account_last4)
    elif ext == "csv":
        return _parse_bank_csv(filepath, account_name, account_last4)
    else:
        return {"success": False, "error": f"Unsupported format: {ext}"}


def persist_statement(statement_data: dict, transactions: list[dict],
                      original_filename: str = "") -> "BankStatement":
    """
    Write a BankStatement + its BankTransaction children to the DB.
    Returns the new BankStatement instance.
    """
    from app.extensions import db
    from app.models.bank import BankStatement, BankTransaction

    stmt = BankStatement(
        account_name=statement_data.get("account_name", ""),
        account_number_last4=statement_data.get("account_number_last4", ""),
        statement_start=_as_date(statement_data.get("statement_start")),
        statement_end=_as_date(statement_data.get("statement_end")),
        file_format=statement_data.get("file_format", "csv"),
        original_filename=original_filename,
        opening_balance=statement_data.get("opening_balance", 0),
        closing_balance=statement_data.get("closing_balance", 0),
        notes=statement_data.get("notes", ""),
    )
    db.session.add(stmt)
    db.session.flush()

    for tx_data in transactions:
        tx = BankTransaction(
            statement_id=stmt.id,
            transaction_date=_as_date(tx_data.get("transaction_date")),
            post_date=_as_date(tx_data.get("post_date")),
            description=tx_data.get("description", ""),
            amount=tx_data.get("amount", 0),
            transaction_type=tx_data.get("transaction_type"),
            check_number=tx_data.get("check_number"),
            reference_number=tx_data.get("reference_number"),
            balance=tx_data.get("balance"),
            category=_auto_categorise(tx_data),
        )
        db.session.add(tx)

    db.session.commit()
    return stmt


# ------------------------------------------------------------------ #
# CSV parser                                                          #
# ------------------------------------------------------------------ #

# Common column name mappings across different banks
_CSV_COL_ALIASES = {
    "transaction_date": ["date", "transaction date", "trans date", "posted date", "trans. date"],
    "post_date":        ["post date", "posting date", "settlement date"],
    "description":      ["description", "memo", "narrative", "transaction description",
                         "details", "payee", "merchant"],
    "amount":           ["amount", "transaction amount", "debit/credit", "net amount"],
    "debit":            ["debit", "withdrawals", "charges", "amount (dr)"],
    "credit":           ["credit", "deposits", "payments", "amount (cr)"],
    "balance":          ["balance", "running balance", "balance after"],
    "check_number":     ["check number", "check #", "chk #", "check no"],
    "reference":        ["reference", "reference number", "ref #", "transaction id"],
}


def _parse_bank_csv(filepath: str, account_name: str = "",
                    account_last4: str = "") -> dict[str, Any]:
    try:
        with open(filepath, newline="", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = [h.strip() for h in (reader.fieldnames or [])]
            col_map = _map_csv_columns(headers)
            transactions = []

            for row in reader:
                tx = _parse_csv_row(row, col_map)
                if tx:
                    transactions.append(tx)

        dates = [t["transaction_date"] for t in transactions if t.get("transaction_date")]
        return {
            "success": True,
            "statement": {
                "account_name": account_name,
                "account_number_last4": account_last4,
                "statement_start": min(dates) if dates else None,
                "statement_end": max(dates) if dates else None,
                "file_format": "csv",
            },
            "transactions": transactions,
            "count": len(transactions),
        }
    except Exception as exc:
        return {"success": False, "error": str(exc), "transactions": []}


def _map_csv_columns(headers: list[str]) -> dict[str, str | None]:
    """Return {field_name: actual_header} for each known field."""
    lower_headers = [h.lower() for h in headers]
    result = {}
    for field, aliases in _CSV_COL_ALIASES.items():
        for alias in aliases:
            if alias in lower_headers:
                result[field] = headers[lower_headers.index(alias)]
                break
        else:
            result[field] = None
    return result


def _parse_csv_row(row: dict, col_map: dict) -> dict | None:
    def get(field):
        col = col_map.get(field)
        return row.get(col, "").strip() if col else ""

    tx_date = _parse_date_str(get("transaction_date"))
    if not tx_date:
        return None

    # Handle split debit/credit columns
    amount_str = get("amount")
    if amount_str:
        amount = _safe_decimal(amount_str)
    else:
        credit = _safe_decimal(get("credit") or "0")
        debit = _safe_decimal(get("debit") or "0")
        amount = credit - debit   # credits positive, debits negative

    check_num = get("check_number")
    tx_type = _infer_type(amount, check_num, get("description"))

    return {
        "transaction_date": tx_date,
        "post_date": _parse_date_str(get("post_date")),
        "description": get("description"),
        "amount": float(amount),
        "transaction_type": tx_type,
        "check_number": check_num or None,
        "reference_number": get("reference") or None,
        "balance": float(_safe_decimal(get("balance"))) if get("balance") else None,
    }


# ------------------------------------------------------------------ #
# OFX/QFX parser                                                     #
# ------------------------------------------------------------------ #

def _parse_ofx(filepath: str, account_name: str = "",
               account_last4: str = "") -> dict[str, Any]:
    try:
        from ofxparse import OfxParser

        with open(filepath, "rb") as f:
            ofx = OfxParser.parse(f)

        account = ofx.account
        transactions = []

        for tx in account.statement.transactions:
            amount = float(tx.amount)
            check_num = getattr(tx, "checknum", None) or ""
            tx_type = _infer_type(Decimal(str(amount)), check_num, tx.memo or tx.payee or "")

            transactions.append({
                "transaction_date": tx.date.date() if tx.date else None,
                "post_date": getattr(tx, "settleDate", None),
                "description": (tx.memo or tx.payee or "").strip(),
                "amount": amount,
                "transaction_type": tx_type,
                "check_number": check_num or None,
                "reference_number": tx.id,
            })

        stmt = account.statement
        return {
            "success": True,
            "statement": {
                "account_name": account_name or str(getattr(account, "account_id", "")),
                "account_number_last4": account_last4 or str(getattr(account, "account_id", ""))[-4:],
                "statement_start": stmt.start_date.date() if stmt.start_date else None,
                "statement_end": stmt.end_date.date() if stmt.end_date else None,
                "opening_balance": float(getattr(stmt, "balance", 0) or 0),
                "closing_balance": float(getattr(stmt, "balance", 0) or 0),
                "file_format": "ofx",
            },
            "transactions": transactions,
            "count": len(transactions),
        }
    except ImportError:
        return {"success": False, "error": "ofxparse not installed. Run: pip install ofxparse"}
    except Exception as exc:
        return {"success": False, "error": str(exc), "transactions": []}


# ------------------------------------------------------------------ #
# Helpers                                                             #
# ------------------------------------------------------------------ #

def _infer_type(amount: Decimal, check_num: str, description: str) -> str:
    desc_upper = description.upper()
    if check_num and check_num.isdigit():
        return "check"
    if "ACH" in desc_upper or "EFT" in desc_upper or "DIRECT DEP" in desc_upper:
        return "eft"
    if "FEE" in desc_upper or "SERVICE CHARGE" in desc_upper:
        return "fee"
    return "credit" if amount > 0 else "debit"


def _auto_categorise(tx_data: dict) -> str:
    desc = (tx_data.get("description") or "").upper()
    tx_type = tx_data.get("transaction_type", "")
    amount = tx_data.get("amount", 0)

    if tx_type == "check":
        return "check_payment"
    if amount > 0:
        if any(k in desc for k in ("OPTUM", "CHANGE", "OFFICEALLY", "INSURANCE", "ANTHEM", "AETNA")):
            return "payment_received"
        return "deposit"
    if any(k in desc for k in ("SPECTRUM", "PETNET", "SUPPLY", "VENDOR")):
        return "vendor_payment"
    return "expense"


def _parse_date_str(val: str) -> date | None:
    if not val:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y", "%m/%d/%y", "%d/%m/%Y"):
        try:
            return datetime.strptime(val.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _as_date(val) -> date | None:
    if val is None:
        return None
    if isinstance(val, date):
        return val
    return _parse_date_str(str(val))


def _safe_decimal(val: str) -> Decimal:
    if not val:
        return Decimal("0")
    cleaned = val.replace("$", "").replace(",", "").replace(" ", "").strip()
    # Handle parentheses for negatives: (100.00) → -100.00
    if cleaned.startswith("(") and cleaned.endswith(")"):
        cleaned = "-" + cleaned[1:-1]
    try:
        return Decimal(cleaned)
    except Exception:
        return Decimal("0")
