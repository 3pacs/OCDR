"""
Candalis connector.

Candalis is a veterinary practice management platform. This connector
logs in to the Candalis portal and downloads patient/appointment/billing data.
Update BASE_URL to match your practice's Candalis instance URL.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError, _parse_date


class CandalisConnector(BaseConnector):
    SLUG = "candalis"
    DISPLAY_NAME = "Candalis"
    BASE_URL = "https://app.candalis.com"   # adjust to your practice URL

    LOGIN_URL = "https://app.candalis.com/login"

    def login(self, page, username: str, password: str, extra: dict) -> None:
        # extra may contain: {"base_url": "https://yourpractice.candalis.com"}
        base_url = extra.get("base_url", self.BASE_URL)
        login_url = f"{base_url}/login"

        page.goto(login_url, wait_until="domcontentloaded")
        page.fill("input[name='email'], input[id*='email'], input[type='email']", username)
        page.fill("input[name='password'], input[type='password']", password)
        page.click("button[type='submit'], input[type='submit']")

        try:
            page.wait_for_url(f"*{base_url}/**", timeout=20_000)
        except Exception:
            error = self.safe_text(page, "[class*='error'], .alert-danger, .flash-error")
            raise ConnectorError(f"Candalis login failed: {error or 'Timeout. Check credentials.'}")

    def fetch_data(self, page, download_dir: str) -> list[dict[str, Any]]:
        records = []
        base_url = self.BASE_URL  # could be overridden via extra

        # --- Billing/invoices ---
        for path in ["/billing", "/invoices", "/reports/billing"]:
            try:
                page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=10_000)
                with page.expect_download(timeout=15_000) as dl:
                    page.click("button:has-text('Export'), a:has-text('CSV')", timeout=5_000)
                dl_path = os.path.join(download_dir, "candalis_billing.csv")
                dl.value.save_as(dl_path)
                records.extend(self._parse_billing_csv(dl_path))
                break
            except Exception:
                continue

        # --- Appointments ---
        for path in ["/appointments/export", "/appointments"]:
            try:
                page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=10_000)
                with page.expect_download(timeout=15_000) as dl:
                    page.click("button:has-text('Export'), a:has-text('CSV')", timeout=5_000)
                dl_path = os.path.join(download_dir, "candalis_appts.csv")
                dl.value.save_as(dl_path)
                records.extend(self._parse_appointment_csv(dl_path))
                break
            except Exception:
                continue

        return records

    def _parse_billing_csv(self, filepath: str) -> list[dict]:
        records = []
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append({
                        "record_type": "claim",
                        "external_id": row.get("Invoice #") or row.get("Invoice ID"),
                        "patient_name": row.get("Patient") or row.get("Client"),
                        "service_date": row.get("Date") or row.get("Service Date"),
                        "billed_amount": self._safe_amount(row.get("Total") or row.get("Charged")),
                        "paid_amount": self._safe_amount(row.get("Paid") or row.get("Amount Paid")),
                        "status": row.get("Status", "pending"),
                        "payer_name": row.get("Insurance") or "Client",
                        "raw": dict(row),
                    })
        except Exception as exc:
            print(f"[Candalis] Billing CSV parse error: {exc}")
        return records

    def _parse_appointment_csv(self, filepath: str) -> list[dict]:
        records = []
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append({
                        "record_type": "appointment",
                        "external_id": row.get("Appointment ID") or row.get("ID"),
                        "patient_name": row.get("Patient") or row.get("Animal"),
                        "service_date": row.get("Date") or row.get("Appointment Date"),
                        "status": row.get("Status", "completed"),
                        "raw": dict(row),
                    })
        except Exception as exc:
            print(f"[Candalis] Appointment CSV parse error: {exc}")
        return records

    def _persist(self, records: list[dict]) -> int:
        from app.extensions import db
        from app.models.payment import Claim

        new = 0
        for r in records:
            if r.get("record_type") not in ("claim",):
                continue  # skip appointments for now (no claim model)
            ext_id = r.get("external_id")
            if ext_id and db.session.execute(
                db.select(Claim).where(Claim.external_id == ext_id,
                                       Claim.source == self.SLUG)
            ).scalar_one_or_none():
                continue
            c = Claim(
                source=self.SLUG,
                external_id=ext_id,
                patient_name=r.get("patient_name"),
                payer_name=r.get("payer_name", "Client"),
                service_date=_parse_date(r.get("service_date")),
                billed_amount=r.get("billed_amount", 0),
                paid_amount=r.get("paid_amount", 0),
                status=r.get("status"),
                raw_data=json.dumps(r.get("raw", {})),
            )
            db.session.add(c)
            new += 1
        db.session.commit()
        return new

    @staticmethod
    def _safe_amount(val) -> float:
        if not val:
            return 0.0
        return float(str(val).replace("$", "").replace(",", "").strip() or 0)
