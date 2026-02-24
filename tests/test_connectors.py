"""
Tests for credential manager, connector registry, bank importer,
reconciliation engine, and connector/reconciliation API routes.
"""
import csv
import io
import json
import tempfile
import os
import pytest
from decimal import Decimal


# ------------------------------------------------------------------ #
# Credential manager                                                  #
# ------------------------------------------------------------------ #

class TestCredentialManager:
    def test_encrypt_decrypt_roundtrip(self, app):
        with app.app_context():
            from app.services.credential_manager import encrypt, decrypt
            plaintext = "super_secret_password_123!"
            ciphertext = encrypt(plaintext)
            assert ciphertext != plaintext
            assert decrypt(ciphertext) == plaintext

    def test_encrypt_empty_string(self, app):
        with app.app_context():
            from app.services.credential_manager import encrypt, decrypt
            assert encrypt("") == ""
            assert decrypt("") == ""

    def test_encrypt_dict_roundtrip(self, app):
        with app.app_context():
            from app.services.credential_manager import encrypt_dict, decrypt_dict
            data = {"base_url": "https://example.com", "org_id": "12345"}
            ct = encrypt_dict(data)
            assert decrypt_dict(ct) == data

    def test_save_and_load_credentials(self, app):
        with app.app_context():
            from app.services.credential_manager import save_credentials, load_credentials
            save_credentials("testconn", "user@test.com", "pass123",
                             extra={"key": "val"}, display_name="Test Conn")
            creds = load_credentials("testconn")
            assert creds is not None
            assert creds["username"] == "user@test.com"
            assert creds["password"] == "pass123"
            assert creds["extra"]["key"] == "val"

    def test_load_missing_credentials_returns_none(self, app):
        with app.app_context():
            from app.services.credential_manager import load_credentials
            assert load_credentials("nonexistent_connector_xyz") is None

    def test_delete_credentials(self, app):
        with app.app_context():
            from app.services.credential_manager import (
                save_credentials, load_credentials, delete_credentials
            )
            save_credentials("delconn", "user", "pass")
            assert load_credentials("delconn") is not None
            result = delete_credentials("delconn")
            assert result is True
            assert load_credentials("delconn") is None


# ------------------------------------------------------------------ #
# Connector registry                                                  #
# ------------------------------------------------------------------ #

class TestConnectorRegistry:
    def test_all_known_slugs_present(self, app):
        with app.app_context():
            from app.connectors.registry import ConnectorRegistry
            slugs = ConnectorRegistry.all_slugs()
            for expected in ["officeally", "optumpay", "changehealth",
                             "spectrumxray_web", "candalis", "purview"]:
                assert expected in slugs

    def test_get_returns_instance(self, app):
        with app.app_context():
            from app.connectors.registry import ConnectorRegistry
            for slug in ConnectorRegistry.all_slugs():
                conn = ConnectorRegistry.get(slug)
                assert conn is not None
                assert conn.SLUG == slug

    def test_get_unknown_returns_none(self, app):
        with app.app_context():
            from app.connectors.registry import ConnectorRegistry
            assert ConnectorRegistry.get("does_not_exist") is None

    def test_meta_has_display_names(self, app):
        with app.app_context():
            from app.connectors.registry import ConnectorRegistry
            meta = ConnectorRegistry.meta()
            assert all("display_name" in m for m in meta)


# ------------------------------------------------------------------ #
# Bank statement importer                                             #
# ------------------------------------------------------------------ #

class TestBankImporter:
    def _make_csv(self, rows: list[dict], fieldnames: list[str]) -> str:
        f = io.StringIO()
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
        tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w")
        tmp.write(f.getvalue())
        tmp.close()
        return tmp.name

    def test_parse_standard_csv(self):
        from app.services.bank_importer import import_bank_file
        path = self._make_csv([
            {"Date": "01/15/2025", "Description": "OPTUM EFT PAYMENT", "Amount": "1500.00"},
            {"Date": "01/16/2025", "Description": "CHECK 1001", "Amount": "-200.00"},
        ], ["Date", "Description", "Amount"])
        try:
            result = import_bank_file(path, "Business Checking", "1234")
            assert result["success"] is True
            assert result["count"] == 2
            assert result["transactions"][0]["amount"] == 1500.0
            assert result["transactions"][1]["amount"] == -200.0
        finally:
            os.unlink(path)

    def test_parse_debit_credit_columns(self):
        from app.services.bank_importer import import_bank_file
        path = self._make_csv([
            {"Date": "02/01/2025", "Description": "Deposit", "Credit": "500.00", "Debit": ""},
            {"Date": "02/02/2025", "Description": "Payment", "Credit": "", "Debit": "100.00"},
        ], ["Date", "Description", "Credit", "Debit"])
        try:
            result = import_bank_file(path)
            assert result["success"] is True
            txns = result["transactions"]
            credits = [t for t in txns if t["amount"] > 0]
            debits = [t for t in txns if t["amount"] < 0]
            assert len(credits) == 1
            assert len(debits) == 1
        finally:
            os.unlink(path)

    def test_auto_categorise_payment_received(self):
        from app.services.bank_importer import _auto_categorise
        tx = {"description": "OPTUM HEALTH EFT", "transaction_type": "eft", "amount": 500}
        assert _auto_categorise(tx) == "payment_received"

    def test_auto_categorise_check(self):
        from app.services.bank_importer import _auto_categorise
        tx = {"description": "Check 1002", "transaction_type": "check", "amount": -50}
        assert _auto_categorise(tx) == "check_payment"

    def test_persist_statement(self, app):
        with app.app_context():
            from app.services.bank_importer import persist_statement
            from datetime import date
            stmt = persist_statement(
                {
                    "account_name": "Test Checking",
                    "account_number_last4": "9999",
                    "statement_start": date(2025, 1, 1),
                    "statement_end": date(2025, 1, 31),
                    "file_format": "csv",
                },
                [
                    {"transaction_date": date(2025, 1, 5), "description": "Deposit",
                     "amount": 1000.0, "transaction_type": "credit"},
                ],
                "test.csv",
            )
            assert stmt.id is not None
            from app.extensions import db
            from app.models.bank import BankTransaction
            txns = db.session.execute(
                db.select(BankTransaction).where(BankTransaction.statement_id == stmt.id)
            ).scalars().all()
            assert len(txns) == 1
            assert float(txns[0].amount) == 1000.0


# ------------------------------------------------------------------ #
# Reconciliation engine                                               #
# ------------------------------------------------------------------ #

class TestReconciliationEngine:
    def _seed_data(self, app):
        """Create a payment + matching bank transaction."""
        from app.extensions import db
        from app.models.payment import Payment
        from app.models.bank import BankStatement, BankTransaction
        from datetime import date

        p = Payment(
            source="optumpay",
            check_number="CHK00123",
            payer_name="Optum",
            payment_date=date(2025, 2, 10),
            amount=750.00,
            payment_type="check",
        )
        db.session.add(p)

        stmt = BankStatement(
            account_name="Test Checking",
            file_format="csv",
        )
        db.session.add(stmt)
        db.session.flush()

        tx = BankTransaction(
            statement_id=stmt.id,
            transaction_date=date(2025, 2, 11),
            description="CHK00123 OPTUM",
            amount=750.00,
            check_number="CHK00123",
            transaction_type="check",
        )
        db.session.add(tx)
        db.session.commit()
        return p, tx

    def test_auto_reconcile_check_match(self, app):
        with app.app_context():
            from app.services.reconciliation import run_auto_reconcile
            p, tx = self._seed_data(app)
            result = run_auto_reconcile()
            assert result["matched"] >= 1

    def test_manual_match(self, app):
        with app.app_context():
            from app.extensions import db
            from app.models.payment import Payment
            from app.models.bank import BankStatement, BankTransaction
            from app.services.reconciliation import manual_match
            from datetime import date

            p = Payment(source="test", amount=100, payment_type="eft",
                        payment_date=date(2025, 3, 1))
            db.session.add(p)
            stmt = BankStatement(account_name="x", file_format="csv")
            db.session.add(stmt)
            db.session.flush()
            tx = BankTransaction(statement_id=stmt.id, transaction_date=date(2025, 3, 1),
                                  description="EFT", amount=100)
            db.session.add(tx)
            db.session.commit()

            result = manual_match(p.id, tx.id, notes="test match")
            assert result["success"] is True
            db.session.refresh(p)
            assert p.status == "reconciled"

    def test_unmatch(self, app):
        with app.app_context():
            from app.extensions import db
            from app.models.payment import Payment
            from app.models.bank import BankStatement, BankTransaction
            from app.services.reconciliation import manual_match, unmatch
            from datetime import date

            p = Payment(source="test2", amount=200, payment_type="eft",
                        payment_date=date(2025, 4, 1))
            db.session.add(p)
            stmt = BankStatement(account_name="y", file_format="csv")
            db.session.add(stmt)
            db.session.flush()
            tx = BankTransaction(statement_id=stmt.id, transaction_date=date(2025, 4, 1),
                                  description="EFT 2", amount=200)
            db.session.add(tx)
            db.session.commit()

            r = manual_match(p.id, tx.id)
            unmatch(r["match_id"])
            db.session.refresh(p)
            assert p.status == "unreconciled"


# ------------------------------------------------------------------ #
# Connector API routes                                                #
# ------------------------------------------------------------------ #

class TestConnectorRoutes:
    def test_list_connectors(self, client):
        res = client.get("/api/connectors/")
        assert res.status_code == 200
        data = res.get_json()
        assert isinstance(data, list)
        slugs = [d["slug"] for d in data]
        assert "officeally" in slugs
        assert "optumpay" in slugs

    def test_save_and_check_credentials(self, client):
        payload = {"username": "user@test.com", "password": "testpass123"}
        res = client.post("/api/connectors/officeally/credentials", json=payload)
        assert res.status_code == 201
        check = client.get("/api/connectors/officeally/credentials")
        assert check.get_json()["configured"] is True

    def test_save_credentials_missing_fields(self, client):
        res = client.post("/api/connectors/optumpay/credentials", json={"username": "u"})
        assert res.status_code == 400

    def test_save_credentials_unknown_connector(self, client):
        res = client.post("/api/connectors/unknown_xyz/credentials",
                          json={"username": "u", "password": "p"})
        assert res.status_code == 404

    def test_delete_credentials(self, client):
        client.post("/api/connectors/candalis/credentials",
                    json={"username": "u", "password": "p"})
        res = client.delete("/api/connectors/candalis/credentials")
        assert res.status_code == 200

    def test_list_payments(self, client):
        res = client.get("/api/connectors/payments")
        assert res.status_code == 200
        assert isinstance(res.get_json(), list)

    def test_all_sync_logs(self, client):
        res = client.get("/api/connectors/logs/all")
        assert res.status_code == 200


# ------------------------------------------------------------------ #
# Reconciliation API routes                                           #
# ------------------------------------------------------------------ #

class TestReconciliationRoutes:
    def _upload_csv_statement(self, client):
        content = (
            "Date,Description,Amount\n"
            "01/05/2025,OPTUM EFT,1200.00\n"
            "01/10/2025,Check 2001,-500.00\n"
        )
        data = {
            "file": (io.BytesIO(content.encode()), "statement.csv", "text/csv"),
            "account_name": "Test Checking",
            "account_last4": "5678",
        }
        return client.post(
            "/api/reconciliation/statements/upload",
            data=data,
            content_type="multipart/form-data",
        )

    def test_upload_statement(self, client):
        res = self._upload_csv_statement(client)
        assert res.status_code == 201
        data = res.get_json()
        assert data["transactions_imported"] == 2

    def test_list_statements(self, client):
        self._upload_csv_statement(client)
        res = client.get("/api/reconciliation/statements")
        assert res.status_code == 200
        assert len(res.get_json()) >= 1

    def test_get_summary(self, client):
        res = client.get("/api/reconciliation/summary")
        assert res.status_code == 200
        data = res.get_json()
        assert "payments_total" in data

    def test_run_reconcile(self, client):
        res = client.post("/api/reconciliation/run",
                          json={}, content_type="application/json")
        assert res.status_code == 200
        assert "matched" in res.get_json()

    def test_get_unmatched(self, client):
        res = client.get("/api/reconciliation/unmatched")
        assert res.status_code == 200
        data = res.get_json()
        assert "unmatched_payments" in data
        assert "unmatched_bank_transactions" in data

    def test_upload_no_file(self, client):
        res = client.post("/api/reconciliation/statements/upload")
        assert res.status_code == 400
