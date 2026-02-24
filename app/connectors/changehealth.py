"""
Change Healthcare (via Optum) connector.

After the 2024 Optum acquisition, Change Healthcare payments are accessible
through the Optum Connect / Change Healthcare portal. This connector handles
login to the Change Healthcare provider portal and downloads ERA/remittance data.
"""
from __future__ import annotations

import csv
import os
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError, _parse_date


class ChangeHealthConnector(BaseConnector):
    SLUG = "changehealth"
    DISPLAY_NAME = "Change Healthcare (Optum)"
    BASE_URL = "https://providers.changehealthcare.com"

    LOGIN_URL = "https://providers.changehealthcare.com/login"

    def login(self, page, username: str, password: str, extra: dict) -> None:
        page.goto(self.LOGIN_URL, wait_until="domcontentloaded")

        page.fill("input[name='username'], input[id*='username'], input[type='email']", username)

        try:
            page.click("button:has-text('Next'), input[value='Next']", timeout=3_000)
        except Exception:
            pass

        page.fill("input[name='password'], input[id*='password'], input[type='password']", password)
        page.click("button[type='submit'], input[type='submit'], button:has-text('Log In')")

        try:
            page.wait_for_url("**/home**", timeout=20_000)
        except Exception:
            error = self.safe_text(page, "[class*='error'], [class*='alert'], .login-error")
            raise ConnectorError(
                f"Change Healthcare login failed: {error or 'Timeout. Verify credentials.'}"
            )

    def fetch_data(self, page, download_dir: str) -> list[dict[str, Any]]:
        records = []

        # Navigate to ERA/Remittance section
        for path in ["/remittance", "/era", "/payments/remittance"]:
            try:
                page.goto(f"{self.BASE_URL}{path}", wait_until="domcontentloaded", timeout=10_000)
                break
            except Exception:
                continue

        # Attempt CSV export
        try:
            with page.expect_download(timeout=20_000) as dl:
                page.click(
                    "button:has-text('Export'), button:has-text('Download'), a:has-text('Export')",
                    timeout=5_000,
                )
            dl_path = os.path.join(download_dir, "changehealth.csv")
            dl.value.save_as(dl_path)
            records.extend(self._parse_csv(dl_path))
        except Exception:
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
            print(f"[ChangeHealth] CSV parse error: {exc}")
        return records

    def _scrape_table(self, page) -> list[dict]:
        rows = page.query_selector_all("table tbody tr")
        records = []
        for row in rows:
            cells = [td.inner_text().strip() for td in row.query_selector_all("td")]
            if len(cells) >= 3:
                records.append({
                    "external_id": cells[0],
                    "payment_date": cells[1] if len(cells) > 1 else None,
                    "amount": self._safe_amount(cells[2] if len(cells) > 2 else "0"),
                    "payer_name": "Change Healthcare",
                    "payment_type": "eft",
                })
        return records

    def _normalise_row(self, row: dict) -> dict:
        trace = (row.get("Trace Number") or row.get("EFT Trace") or
                 row.get("Check Number") or row.get("Payment ID") or "")
        return {
            "external_id": trace,
            "check_number": trace if trace.startswith("CHK") else None,
            "eft_trace_number": trace if not trace.startswith("CHK") else None,
            "payer_name": row.get("Payer Name") or row.get("Insurance") or "Change Healthcare",
            "payer_id": row.get("Payer ID") or row.get("NPI"),
            "payment_date": row.get("Payment Date") or row.get("Issue Date"),
            "amount": self._safe_amount(row.get("Amount") or row.get("Payment Amount")),
            "payment_type": "check" if trace.startswith("CHK") else "eft",
            "memo": row.get("Memo") or row.get("Notes"),
            "raw": dict(row),
        }

    @staticmethod
    def _safe_amount(val) -> float:
        if not val:
            return 0.0
        return float(str(val).replace("$", "").replace(",", "").strip() or 0)
