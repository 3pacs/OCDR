"""
Purview connector.

"Purview" may refer to your practice's specific reporting or analytics portal.
Update BASE_URL, LOGIN_URL, and the selectors to match the actual site.
The connector structure is fully generic — override fetch_data for
custom navigation.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError, _parse_date


class PurviewConnector(BaseConnector):
    SLUG = "purview"
    DISPLAY_NAME = "Purview"
    BASE_URL = "https://app.purview.net"   # ← update to your Purview URL

    LOGIN_URL = "https://app.purview.net/login"

    def login(self, page, username: str, password: str, extra: dict) -> None:
        base_url = extra.get("base_url", self.BASE_URL)
        login_url = extra.get("login_url", f"{base_url}/login")

        page.goto(login_url, wait_until="domcontentloaded")
        page.fill("input[name='username'], input[type='email'], input[id*='user']", username)
        page.fill("input[type='password'], input[name='password']", password)
        page.click("button[type='submit'], input[type='submit'], button:has-text('Sign In')")

        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
            # Verify we're past the login page
            if "login" in page.url.lower():
                raise Exception("Still on login page")
        except Exception:
            error = self.safe_text(page, "[class*='error'], .alert, #error-message")
            raise ConnectorError(f"Purview login failed: {error or 'Timeout. Check URL and credentials.'}")

    def fetch_data(self, page, download_dir: str) -> list[dict[str, Any]]:
        records = []
        base_url = self.BASE_URL

        # Try common report export paths
        report_paths = [
            "/reports", "/analytics", "/reports/export",
            "/dashboard/export", "/data-export",
        ]

        for path in report_paths:
            try:
                page.goto(f"{base_url}{path}", wait_until="domcontentloaded", timeout=10_000)
                with page.expect_download(timeout=20_000) as dl:
                    page.click(
                        "button:has-text('Export'), a:has-text('Export'), "
                        "button:has-text('Download'), a:has-text('CSV')",
                        timeout=5_000,
                    )
                ext = dl.value.suggested_filename.rsplit(".", 1)[-1].lower()
                dl_path = os.path.join(download_dir, f"purview_export.{ext}")
                dl.value.save_as(dl_path)

                if ext == "csv":
                    records.extend(self._parse_csv(dl_path))
                break
            except Exception:
                continue

        return records

    def _parse_csv(self, filepath: str) -> list[dict]:
        records = []
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append({
                        "record_type": "report_row",
                        "external_id": row.get("ID") or row.get("Record ID"),
                        "raw": dict(row),
                    })
        except Exception as exc:
            print(f"[Purview] CSV parse error: {exc}")
        return records

    def _persist(self, records: list[dict]) -> int:
        """Store Purview rows as raw Document records for manual review."""
        from app.extensions import db
        from app.models.document import Document
        import json

        new = 0
        for r in records:
            doc = Document(
                filename=f"purview_{r.get('external_id', 'row')}.json",
                original_filename="purview_export.csv",
                file_type="json",
                category="report",
                notes=json.dumps(r.get("raw", {}))[:500],
            )
            db.session.add(doc)
            new += 1
        db.session.commit()
        return new
