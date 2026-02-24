"""
SpectrumXray web connector — logs in and pulls order history directly.

Complements the existing file-based SpectrumXray vendor (CSV upload).
This connector automates browser login to download order history without
manual CSV exports.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError, _parse_date


class SpectrumXrayWebConnector(BaseConnector):
    SLUG = "spectrumxray_web"
    DISPLAY_NAME = "SpectrumXray (Auto-Sync)"
    BASE_URL = "https://www.spectrumxray.com"

    LOGIN_URL = "https://www.spectrumxray.com/login"

    def login(self, page, username: str, password: str, extra: dict) -> None:
        page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
        page.fill("input[name*='user'], input[id*='user'], input[name='email']", username)
        page.fill("input[type='password'], input[name*='pass']", password)
        page.click("button[type='submit'], input[type='submit'], button:has-text('Log In')")

        try:
            page.wait_for_url("**/account**", timeout=15_000)
        except Exception:
            error = self.safe_text(page, "[class*='error'], .alert-danger")
            raise ConnectorError(f"SpectrumXray login failed: {error or 'Timeout.'}")

    def fetch_data(self, page, download_dir: str) -> list[dict[str, Any]]:
        records = []

        # Navigate to order history
        for path in ["/account/orders", "/orders", "/account/order-history"]:
            try:
                page.goto(f"{self.BASE_URL}{path}", wait_until="domcontentloaded", timeout=10_000)
                break
            except Exception:
                continue

        # Try export button
        try:
            with page.expect_download(timeout=15_000) as dl:
                page.click("button:has-text('Export'), a:has-text('Download')", timeout=5_000)
            dl_path = os.path.join(download_dir, "spectrumxray_orders.csv")
            dl.value.save_as(dl_path)
            records.extend(self._parse_order_csv(dl_path))
        except Exception:
            records.extend(self._scrape_order_table(page))

        return records

    def _parse_order_csv(self, filepath: str) -> list[dict]:
        records = []
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append(self._normalise_row(row))
        except Exception as exc:
            print(f"[SpectrumXray] CSV parse error: {exc}")
        return records

    def _scrape_order_table(self, page) -> list[dict]:
        rows = page.query_selector_all("table tbody tr, [class*='order-row']")
        records = []
        for row in rows:
            cells = [td.inner_text().strip() for td in row.query_selector_all("td")]
            if len(cells) >= 3:
                records.append({
                    "record_type": "purchase",
                    "external_id": cells[0],
                    "order_date": cells[1] if len(cells) > 1 else None,
                    "total": self._safe_amount(cells[-1]),
                    "status": "received",
                })
        return records

    def _normalise_row(self, row: dict) -> dict:
        return {
            "record_type": "purchase",
            "external_id": row.get("Order #") or row.get("Order Number") or row.get("PO"),
            "order_date": row.get("Order Date") or row.get("Date"),
            "total": self._safe_amount(row.get("Total") or row.get("Order Total")),
            "status": row.get("Status", "received"),
            "raw": dict(row),
        }

    # ---------------------------------------------------------------- #
    # Persist as Purchase records                                       #
    # ---------------------------------------------------------------- #

    def _persist(self, records: list[dict]) -> int:
        from app.extensions import db
        from app.models.purchase import Purchase
        from app.models.vendor import Vendor

        vendor = db.session.execute(
            db.select(Vendor).where(Vendor.slug == "spectrumxray")
        ).scalar_one_or_none()
        vendor_id = vendor.id if vendor else None

        new = 0
        for r in records:
            ext_id = r.get("external_id")
            if not ext_id:
                continue
            exists = db.session.execute(
                db.select(Purchase).where(Purchase.order_number == ext_id)
            ).scalar_one_or_none()
            if exists:
                continue

            p = Purchase(
                vendor_id=vendor_id,
                order_number=ext_id,
                order_date=_parse_date(r.get("order_date")),
                status=r.get("status", "received"),
                total=r.get("total", 0),
                source="spectrumxray_web",
            )
            db.session.add(p)
            new += 1

        db.session.commit()
        return new

    @staticmethod
    def _safe_amount(val) -> float:
        if not val:
            return 0.0
        return float(str(val).replace("$", "").replace(",", "").strip() or 0)
