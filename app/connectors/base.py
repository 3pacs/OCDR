"""
Abstract base class for all third-party site connectors.

Each connector uses Playwright (sync API) to:
  1. Log in to the target site
  2. Navigate to the relevant export/report page
  3. Download or scrape data
  4. Return normalised records for storage

The base class handles:
  - Browser lifecycle (launch → login → work → close)
  - Sync log creation/update
  - Credential loading
  - Common helpers (wait, click, fill, download)
"""
from __future__ import annotations

import json
import os
import tempfile
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any


class ConnectorError(Exception):
    """Raised when a connector fails with a user-facing message."""


class BaseConnector(ABC):
    SLUG: str = ""
    DISPLAY_NAME: str = ""
    BASE_URL: str = ""

    # ---------------------------------------------------------------- #
    # Required interface                                                #
    # ---------------------------------------------------------------- #

    @abstractmethod
    def login(self, page, username: str, password: str, extra: dict) -> None:
        """Fill the login form and wait for post-login state."""

    @abstractmethod
    def fetch_data(self, page, download_dir: str) -> list[dict[str, Any]]:
        """
        Navigate to the export page, trigger downloads, and return
        a list of normalised record dicts ready for DB insertion.
        """

    # ---------------------------------------------------------------- #
    # Orchestration (called by sync service)                           #
    # ---------------------------------------------------------------- #

    def run_sync(self, app_context=None) -> dict[str, Any]:
        """
        Full sync cycle:
          1. Load credentials
          2. Launch browser
          3. Login
          4. Fetch data
          5. Persist records
          6. Return summary
        """
        from app.services.credential_manager import load_credentials

        creds = load_credentials(self.SLUG)
        if creds is None:
            raise ConnectorError(f"No credentials saved for {self.SLUG}. Please configure them first.")

        log = self._start_log()

        try:
            from playwright.sync_api import sync_playwright

            with tempfile.TemporaryDirectory() as dl_dir:
                with sync_playwright() as pw:
                    browser = pw.chromium.launch(
                        headless=True,
                        args=["--disable-blink-features=AutomationControlled"],
                    )
                    context = browser.new_context(
                        accept_downloads=True,
                        viewport={"width": 1280, "height": 900},
                    )
                    page = context.new_page()
                    page.set_default_timeout(30_000)

                    self.login(page, creds["username"], creds["password"], creds["extra"])
                    records = self.fetch_data(page, dl_dir)
                    browser.close()

            new_count = self._persist(records)
            self._finish_log(log, status="success",
                             fetched=len(records), new=new_count)
            self._update_last_sync()
            return {"success": True, "fetched": len(records), "new": new_count}

        except ConnectorError:
            raise
        except Exception as exc:
            self._finish_log(log, status="failed", error=str(exc))
            raise ConnectorError(f"Sync failed for {self.SLUG}: {exc}") from exc

    # ---------------------------------------------------------------- #
    # Persistence hook — subclasses may override                       #
    # ---------------------------------------------------------------- #

    def _persist(self, records: list[dict]) -> int:
        """
        Default: store records as Payment rows. Override in subclasses
        that produce Claims, PurchaseItems, etc.
        """
        from app.extensions import db
        from app.models.payment import Payment

        new = 0
        for r in records:
            ext_id = r.get("external_id")
            if ext_id:
                exists = db.session.execute(
                    db.select(Payment).where(
                        Payment.external_id == ext_id,
                        Payment.source == self.SLUG,
                    )
                ).scalar_one_or_none()
                if exists:
                    continue

            p = Payment(
                source=self.SLUG,
                external_id=r.get("external_id"),
                check_number=r.get("check_number"),
                eft_trace_number=r.get("eft_trace_number"),
                payer_name=r.get("payer_name"),
                payer_id=r.get("payer_id"),
                payment_date=_parse_date(r.get("payment_date")),
                payment_type=r.get("payment_type", "eft"),
                amount=r.get("amount", 0),
                memo=r.get("memo"),
                raw_data=json.dumps(r),
            )
            db.session.add(p)
            new += 1

        db.session.commit()
        return new

    # ---------------------------------------------------------------- #
    # Sync log helpers                                                  #
    # ---------------------------------------------------------------- #

    def _start_log(self):
        from app.extensions import db
        from app.models.connector import ConnectorCredential, ConnectorSyncLog

        cred = db.session.execute(
            db.select(ConnectorCredential).where(
                ConnectorCredential.connector_slug == self.SLUG
            )
        ).scalar_one_or_none()

        log = ConnectorSyncLog(
            credential_id=cred.id if cred else None,
            status="running",
        )
        db.session.add(log)
        db.session.commit()
        return log

    def _finish_log(self, log, status: str, fetched: int = 0,
                    new: int = 0, error: str | None = None) -> None:
        from app.extensions import db

        log.status = status
        log.records_fetched = fetched
        log.records_new = new
        log.error = error
        log.finished_at = datetime.now(timezone.utc)
        db.session.commit()

    def _update_last_sync(self) -> None:
        from app.extensions import db
        from app.models.connector import ConnectorCredential

        cred = db.session.execute(
            db.select(ConnectorCredential).where(
                ConnectorCredential.connector_slug == self.SLUG
            )
        ).scalar_one_or_none()
        if cred:
            cred.last_sync_at = datetime.now(timezone.utc)
            db.session.commit()

    # ---------------------------------------------------------------- #
    # Playwright helpers for subclasses                                #
    # ---------------------------------------------------------------- #

    def wait_and_click(self, page, selector: str, timeout: int = 10_000) -> None:
        page.wait_for_selector(selector, timeout=timeout)
        page.click(selector)

    def safe_text(self, page, selector: str, default: str = "") -> str:
        try:
            el = page.query_selector(selector)
            return el.inner_text().strip() if el else default
        except Exception:
            return default

    def __repr__(self) -> str:
        return f"<Connector:{self.SLUG}>"


# ------------------------------------------------------------------ #
# Internal helpers                                                    #
# ------------------------------------------------------------------ #

def _parse_date(value):
    if not value:
        return None
    from datetime import date
    from dateutil import parser as dp
    if isinstance(value, date):
        return value
    try:
        return dp.parse(str(value)).date()
    except Exception:
        return None
