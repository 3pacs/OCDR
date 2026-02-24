"""
OptumPay connector.

OptumPay (myoptumhealthfinancial.com / optumpay.com) provides EFT/check
remittance data for healthcare providers. This connector logs in, navigates
to the payment history, and downloads remittance reports.
"""
from __future__ import annotations

import csv
import os
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError, _parse_date


class OptumPayConnector(BaseConnector):
    SLUG = "optumpay"
    DISPLAY_NAME = "OptumPay"
    BASE_URL = "https://myoptumhealthfinancial.com"

    LOGIN_URL = "https://myoptumhealthfinancial.com/login"

    def login(self, page, username: str, password: str, extra: dict) -> None:
        page.goto(self.LOGIN_URL, wait_until="domcontentloaded")

        # Fill username
        page.fill("input[name*='user'], input[id*='user'], input[type='email']", username)

        # Click Next if username-first flow
        try:
            page.click("button:has-text('Next'), input[value='Next']", timeout=3_000)
        except Exception:
            pass

        # Fill password
        page.fill("input[name*='pass'], input[id*='pass'], input[type='password']", password)
        page.click("button[type='submit'], input[type='submit'], button:has-text('Sign In')")

        try:
            page.wait_for_url("**/dashboard**", timeout=20_000)
        except Exception:
            error = self.safe_text(page, "[class*='error'], [class*='alert']")
            raise ConnectorError(
                f"OptumPay login failed: {error or 'Timeout waiting for dashboard.'}"
            )

    def fetch_data(self, page, download_dir: str) -> list[dict[str, Any]]:
        records = []

        # Navigate to payment history
        try:
            page.goto(f"{self.BASE_URL}/payments", wait_until="domcontentloaded")
        except Exception:
            page.goto(f"{self.BASE_URL}/payment-history", wait_until="domcontentloaded")

        # Try to export
        try:
            with page.expect_download(timeout=15_000) as dl:
                page.click("button:has-text('Export'), button:has-text('Download')", timeout=5_000)
            dl_path = os.path.join(download_dir, "optumpay.csv")
            dl.value.save_as(dl_path)
            records.extend(self._parse_csv(dl_path))
        except Exception:
            # Fallback: scrape the payment table
            records.extend(self._scrape_table(page))

        return records

    def _parse_csv(self, filepath: str) -> list[dict]:
        records = []
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(self._normalise_row(row))
        except Exception as exc:
            print(f"[OptumPay] CSV parse error: {exc}")
        return records

    def _scrape_table(self, page) -> list[dict]:
        rows = page.query_selector_all("table tbody tr, [class*='payment-row']")
        records = []
        for row in rows:
            cells = [td.inner_text().strip() for td in row.query_selector_all("td")]
            if len(cells) >= 3:
                records.append({
                    "external_id": cells[0],
                    "payment_date": cells[1] if len(cells) > 1 else None,
                    "amount": self._safe_amount(cells[2] if len(cells) > 2 else "0"),
                    "payer_name": "Optum",
                    "payment_type": "eft",
                })
        return records

    def _normalise_row(self, row: dict) -> dict:
        check_or_eft = (row.get("Check/EFT Number") or row.get("Payment Number")
                        or row.get("Trace Number") or "")
        return {
            "external_id": check_or_eft,
            "check_number": check_or_eft if "CHK" in check_or_eft.upper() else None,
            "eft_trace_number": check_or_eft if "CHK" not in check_or_eft.upper() else None,
            "payer_name": row.get("Payer") or row.get("Insurance") or "Optum",
            "payment_date": row.get("Payment Date") or row.get("Issue Date"),
            "amount": self._safe_amount(row.get("Amount") or row.get("Payment Amount")),
            "payment_type": "check" if "CHK" in check_or_eft.upper() else "eft",
            "memo": row.get("Notes") or row.get("Memo"),
            "raw": dict(row),
        }

    @staticmethod
    def _safe_amount(val) -> float:
        if not val:
            return 0.0
        return float(str(val).replace("$", "").replace(",", "").strip() or 0)
