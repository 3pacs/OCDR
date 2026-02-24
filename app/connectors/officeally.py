"""
OfficeAlly connector.

OfficeAlly (officeally.com) is a medical billing / practice management portal.
This connector logs in, navigates to the Claims and Payments reports, and
downloads CSV exports for local storage.

Selector notes are based on the OfficeAlly web UI as of 2024. If the site
updates its layout, update the selectors below.
"""
from __future__ import annotations

import csv
import json
import os
from typing import Any

from app.connectors.base import BaseConnector, ConnectorError, _parse_date


class OfficeAllyConnector(BaseConnector):
    SLUG = "officeally"
    DISPLAY_NAME = "OfficeAlly"
    BASE_URL = "https://pm.officeally.com"

    LOGIN_URL = "https://pm.officeally.com/pm/login.aspx"

    # ---------------------------------------------------------------- #
    # Login                                                             #
    # ---------------------------------------------------------------- #

    def login(self, page, username: str, password: str, extra: dict) -> None:
        page.goto(self.LOGIN_URL, wait_until="domcontentloaded")
        page.fill("#txtUserName", username)
        page.fill("#txtPassword", password)
        page.click("#btnLogin")
        # Wait for the dashboard to load
        try:
            page.wait_for_url("**/pm/**", timeout=20_000)
        except Exception:
            # Check for error message on login page
            error = self.safe_text(page, "#lblError")
            raise ConnectorError(
                f"OfficeAlly login failed: {error or 'Unknown error. Check credentials.'}"
            )

    # ---------------------------------------------------------------- #
    # Data fetching                                                     #
    # ---------------------------------------------------------------- #

    def fetch_data(self, page, download_dir: str) -> list[dict[str, Any]]:
        records = []

        # --- Payments/ERA report ---
        try:
            records.extend(self._fetch_payments(page, download_dir))
        except Exception as exc:
            # Non-fatal: log and continue
            print(f"[OfficeAlly] Payment fetch error: {exc}")

        # --- Claims report ---
        try:
            records.extend(self._fetch_claims(page, download_dir))
        except Exception as exc:
            print(f"[OfficeAlly] Claims fetch error: {exc}")

        return records

    def _fetch_payments(self, page, download_dir: str) -> list[dict]:
        """Navigate to ERA/Payment posting and export."""
        page.goto(f"{self.BASE_URL}/pm/Payments/PaymentPosting.aspx",
                  wait_until="domcontentloaded")

        # Click Export / Download button if available
        try:
            with page.expect_download(timeout=15_000) as dl:
                page.click("input[value*='Export'], button:has-text('Export')", timeout=5_000)
            dl_path = os.path.join(download_dir, "oa_payments.csv")
            dl.value.save_as(dl_path)
            return self._parse_payment_csv(dl_path)
        except Exception:
            # Fallback: scrape table rows directly
            return self._scrape_payment_table(page)

    def _fetch_claims(self, page, download_dir: str) -> list[dict]:
        """Navigate to claims list and export."""
        page.goto(f"{self.BASE_URL}/pm/Claims/ClaimStatus.aspx",
                  wait_until="domcontentloaded")
        try:
            with page.expect_download(timeout=15_000) as dl:
                page.click("input[value*='Export'], button:has-text('Export')", timeout=5_000)
            dl_path = os.path.join(download_dir, "oa_claims.csv")
            dl.value.save_as(dl_path)
            return self._parse_claim_csv(dl_path)
        except Exception:
            return []

    # ---------------------------------------------------------------- #
    # Parsers                                                           #
    # ---------------------------------------------------------------- #

    def _parse_payment_csv(self, filepath: str) -> list[dict]:
        records = []
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append({
                        "record_type": "payment",
                        "external_id": row.get("Check/EFT #") or row.get("Payment ID"),
                        "check_number": row.get("Check/EFT #") or row.get("Check Number"),
                        "payer_name": row.get("Insurance") or row.get("Payer"),
                        "payment_date": row.get("Check Date") or row.get("Payment Date"),
                        "amount": self._safe_amount(row.get("Amount") or row.get("Payment Amount")),
                        "payment_type": "eft" if "EFT" in str(row.get("Check/EFT #", "")).upper() else "check",
                        "memo": row.get("Notes") or row.get("Memo"),
                        "raw": row,
                    })
        except Exception as exc:
            print(f"[OfficeAlly] Payment CSV parse error: {exc}")
        return records

    def _parse_claim_csv(self, filepath: str) -> list[dict]:
        records = []
        try:
            with open(filepath, newline="", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    records.append({
                        "record_type": "claim",
                        "external_id": row.get("Claim ID") or row.get("Claim #"),
                        "patient_name": row.get("Patient Name") or row.get("Patient"),
                        "payer_name": row.get("Insurance") or row.get("Payer"),
                        "service_date": row.get("Service Date") or row.get("DOS"),
                        "billed_amount": self._safe_amount(row.get("Billed Amount") or row.get("Charged")),
                        "paid_amount": self._safe_amount(row.get("Paid Amount") or row.get("Paid")),
                        "status": row.get("Claim Status") or row.get("Status"),
                        "raw": row,
                    })
        except Exception as exc:
            print(f"[OfficeAlly] Claim CSV parse error: {exc}")
        return records

    def _scrape_payment_table(self, page) -> list[dict]:
        rows = page.query_selector_all("table tr")
        records = []
        for row in rows[1:]:  # skip header
            cells = [td.inner_text().strip() for td in row.query_selector_all("td")]
            if len(cells) >= 4:
                records.append({
                    "record_type": "payment",
                    "external_id": cells[0] if cells else None,
                    "payer_name": cells[1] if len(cells) > 1 else None,
                    "payment_date": cells[2] if len(cells) > 2 else None,
                    "amount": self._safe_amount(cells[3] if len(cells) > 3 else "0"),
                })
        return records

    # ---------------------------------------------------------------- #
    # Persistence override — split payments from claims                #
    # ---------------------------------------------------------------- #

    def _persist(self, records: list[dict]) -> int:
        from app.extensions import db
        from app.models.payment import Payment, Claim

        new = 0
        for r in records:
            if r.get("record_type") == "claim":
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
                    payer_name=r.get("payer_name"),
                    service_date=_parse_date(r.get("service_date")),
                    billed_amount=r.get("billed_amount", 0),
                    paid_amount=r.get("paid_amount", 0),
                    status=r.get("status"),
                    raw_data=json.dumps(r.get("raw", {})),
                )
                db.session.add(c)
                new += 1
            else:
                new += self._persist_payment(r)

        db.session.commit()
        return new

    def _persist_payment(self, r: dict) -> int:
        from app.extensions import db
        from app.models.payment import Payment

        ext_id = r.get("external_id")
        if ext_id and db.session.execute(
            db.select(Payment).where(Payment.external_id == ext_id,
                                     Payment.source == self.SLUG)
        ).scalar_one_or_none():
            return 0
        p = Payment(
            source=self.SLUG,
            external_id=ext_id,
            check_number=r.get("check_number"),
            payer_name=r.get("payer_name"),
            payment_date=_parse_date(r.get("payment_date")),
            payment_type=r.get("payment_type", "check"),
            amount=r.get("amount", 0),
            memo=r.get("memo"),
            raw_data=json.dumps(r.get("raw", {})),
        )
        db.session.add(p)
        return 1

    @staticmethod
    def _safe_amount(val) -> float:
        if not val:
            return 0.0
        return float(str(val).replace("$", "").replace(",", "").strip() or 0)
