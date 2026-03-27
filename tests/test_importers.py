"""Tests for import engines (F-01, F-12) and backup (F-20)."""

import csv
import os
import tempfile
import unittest
from datetime import date

from app import create_app
from app.models import db, BillingRecord, ScheduleRecord


class TestCSVImporter(unittest.TestCase):
    """Test CSV auto-detection and import."""

    def setUp(self):
        self.app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
        )
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def _write_csv(self, headers, rows):
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(headers)
            for row in rows:
                writer.writerow(row)
        return path

    def test_billing_csv_import(self):
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient Name", "Doctor", "Scan Type", "Modality", "Service Date", "Total Payment", "Insurance"],
            [
                ["SMITH, JOHN", "DR. A", "BRAIN MRI", "HMRI", "01/15/2024", "750.00", "M/M"],
                ["JONES, MARY", "DR. B", "CT CHEST", "CT", "01/20/2024", "395.00", "INS"],
            ]
        )
        result = import_csv(path)
        self.assertEqual(result["record_type"], "billing")
        self.assertEqual(result["imported"], 2)
        self.assertEqual(BillingRecord.query.count(), 2)
        os.unlink(path)

    def test_schedule_csv_import(self):
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient Name", "Scan Type", "Modality", "Scheduled Date", "Scheduled Time", "Status"],
            [
                ["DOE, JANE", "BRAIN MRI", "HMRI", "03/01/2024", "09:00", "SCHEDULED"],
            ]
        )
        result = import_csv(path)
        self.assertEqual(result["record_type"], "schedule")
        self.assertEqual(result["imported"], 1)
        self.assertEqual(ScheduleRecord.query.count(), 1)
        os.unlink(path)

    def test_empty_csv(self):
        from app.import_engine.csv_importer import import_csv
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)
        result = import_csv(path)
        self.assertTrue(len(result["errors"]) > 0)
        os.unlink(path)

    def test_skips_bad_rows(self):
        from app.import_engine.csv_importer import import_csv
        path = self._write_csv(
            ["Patient Name", "Doctor", "Scan Type", "Modality", "Service Date", "Total Payment"],
            [
                ["SMITH, JOHN", "DR. A", "MRI", "HMRI", "01/15/2024", "750"],
                ["", "", "", "", "", ""],  # blank row — should skip
                ["JONES, MARY", "DR. B", "CT", "CT", "bad_date", "395"],  # bad date — skip
            ]
        )
        result = import_csv(path)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 2)
        os.unlink(path)


class TestExcelImporter(unittest.TestCase):
    """Test Excel billing import."""

    def setUp(self):
        self.app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
        )
        self.ctx = self.app.app_context()
        self.ctx.push()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_import_excel_creates_records(self):
        """Test with a minimal Excel file."""
        from openpyxl import Workbook
        from app.import_engine.excel_importer import import_excel

        wb = Workbook()
        ws = wb.active
        ws.title = "Current"
        ws.append(["Patient", "Doctor", "Scan", "Modality", "Date", "Total", "Insurance"])
        ws.append(["SMITH, JOHN", "DR. A", "BRAIN MRI", "HMRI", "01/15/2024", 750.0, "M/M"])
        ws.append(["JONES, MARY", "DR. B", "CT CHEST", "CT", "01/20/2024", 395.0, "INS"])

        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(path)

        result = import_excel(path)
        self.assertEqual(result["imported"], 2)
        self.assertEqual(result["errors"], [])
        self.assertEqual(BillingRecord.query.count(), 2)

        # Check modality normalization
        rec = BillingRecord.query.filter_by(patient_name="SMITH, JOHN").first()
        self.assertEqual(rec.modality, "HMRI")
        self.assertEqual(rec.total_payment, 750.0)
        self.assertEqual(rec.import_source, "EXCEL_IMPORT")

        os.unlink(path)

    def test_deduplication(self):
        """Test that duplicate records are skipped."""
        from openpyxl import Workbook
        from app.import_engine.excel_importer import import_excel

        wb = Workbook()
        ws = wb.active
        ws.append(["Patient", "Doctor", "Scan", "Modality", "Date", "Total"])
        ws.append(["SMITH, JOHN", "DR. A", "MRI", "HMRI", "01/15/2024", 750.0])
        ws.append(["SMITH, JOHN", "DR. A", "MRI", "HMRI", "01/15/2024", 750.0])  # duplicate

        fd, path = tempfile.mkstemp(suffix=".xlsx")
        os.close(fd)
        wb.save(path)

        result = import_excel(path)
        self.assertEqual(result["imported"], 1)
        self.assertEqual(result["skipped"], 1)
        os.unlink(path)


class TestBackupManager(unittest.TestCase):
    """Test backup functionality."""

    def test_run_backup(self):
        from app.infra.backup_manager import run_backup, verify_backup, get_backup_history

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake db file
            db_path = os.path.join(tmpdir, "ocdr.db")
            with open(db_path, "w") as f:
                f.write("test database content")

            backup_dir = os.path.join(tmpdir, "backups")

            result = run_backup(db_path=db_path, backup_dir=backup_dir)
            self.assertIn("filepath", result)
            self.assertIn("sha256", result)
            self.assertTrue(os.path.exists(result["filepath"]))

            # Verify
            verify = verify_backup(result["filepath"])
            self.assertTrue(verify["valid"])

            # History
            history = get_backup_history(backup_dir)
            self.assertEqual(history["total"], 1)


class TestCSVExporter(unittest.TestCase):
    """Test CSV export functionality."""

    def setUp(self):
        self.app = create_app(
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
        )
        self.ctx = self.app.app_context()
        self.ctx.push()

        db.session.add(BillingRecord(
            patient_name="TEST", referring_doctor="DR. X",
            scan_type="MRI", modality="HMRI",
            insurance_carrier="M/M", service_date=date(2024, 1, 1),
            total_payment=500.0,
        ))
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.ctx.pop()

    def test_export_billing_csv(self):
        from app.export.csv_exporter import export_billing_csv

        with tempfile.TemporaryDirectory() as tmpdir:
            outpath = os.path.join(tmpdir, "test_export.csv")
            result = export_billing_csv(output_path=outpath)
            self.assertEqual(result["record_count"], 1)
            self.assertTrue(os.path.exists(outpath))

            # Verify CSV content
            with open(outpath) as f:
                reader = csv.reader(f)
                headers = next(reader)
                self.assertEqual(headers[0], "Patient")
                row = next(reader)
                self.assertEqual(row[0], "TEST")


if __name__ == "__main__":
    unittest.main()
