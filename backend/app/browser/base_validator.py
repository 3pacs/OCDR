"""Base browser validator framework.

Provides shared infrastructure for all portal validators:
- Browser lifecycle (launch, login, close)
- Screenshot capture
- Result collection and DB comparison
- Credential management from environment
"""

import asyncio
import logging
import os
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SCREENSHOT_DIR = Path(os.environ.get("DATA_DIR", "/app/data")) / "browser-screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)


class ValidationResult:
    """Single comparison result between portal data and DB data."""

    def __init__(
        self,
        record_id: str,
        field: str,
        db_value: Any,
        portal_value: Any,
        match: bool,
        notes: str = "",
    ):
        self.record_id = record_id
        self.field = field
        self.db_value = db_value
        self.portal_value = portal_value
        self.match = match
        self.notes = notes
        self.timestamp = datetime.utcnow().isoformat()

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "field": self.field,
            "db_value": str(self.db_value) if self.db_value is not None else None,
            "portal_value": str(self.portal_value) if self.portal_value is not None else None,
            "match": self.match,
            "notes": self.notes,
            "timestamp": self.timestamp,
        }


class ValidationSummary:
    """Aggregated results from a validation run."""

    def __init__(self, validator_name: str, portal_url: str):
        self.validator_name = validator_name
        self.portal_url = portal_url
        self.results: list[ValidationResult] = []
        self.errors: list[str] = []
        self.screenshots: list[str] = []
        self.started_at = datetime.utcnow().isoformat()
        self.completed_at: str | None = None
        self.status = "running"

    def add_result(self, result: ValidationResult):
        self.results.append(result)

    def add_error(self, error: str):
        self.errors.append(error)

    def add_screenshot(self, path: str):
        self.screenshots.append(path)

    def finalize(self, status: str = "completed"):
        self.completed_at = datetime.utcnow().isoformat()
        self.status = status

    def to_dict(self) -> dict:
        total = len(self.results)
        matched = sum(1 for r in self.results if r.match)
        mismatched = total - matched
        return {
            "validator": self.validator_name,
            "portal_url": self.portal_url,
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "total_checked": total,
            "matched": matched,
            "mismatched": mismatched,
            "match_rate": f"{(matched / total * 100):.1f}%" if total > 0 else "N/A",
            "errors": self.errors,
            "screenshots": self.screenshots,
            "results": [r.to_dict() for r in self.results],
            "mismatches": [r.to_dict() for r in self.results if not r.match],
        }


class BaseValidator(ABC):
    """Abstract base for portal validators.

    Subclasses implement portal-specific login and data extraction.
    The base handles browser lifecycle, screenshots, and result aggregation.
    """

    def __init__(self, portal_url: str, headless: bool = True):
        self.portal_url = portal_url
        self.headless = headless
        self.browser = None
        self.page = None
        self.summary: ValidationSummary | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable validator name."""

    @abstractmethod
    def _get_credentials(self) -> tuple[str, str]:
        """Return (username, password) from environment variables."""

    @abstractmethod
    async def _login(self, page) -> bool:
        """Log into the portal. Return True on success."""

    @abstractmethod
    async def _extract_portal_data(self, page, records: list[dict]) -> list[dict]:
        """Extract portal data for the given DB records.

        Returns list of dicts with portal-side values for comparison.
        Each dict should have 'record_id' plus field values.
        """

    @abstractmethod
    def _compare(self, db_record: dict, portal_record: dict) -> list[ValidationResult]:
        """Compare a DB record against portal data. Return list of field-level results."""

    async def _take_screenshot(self, page, label: str) -> str:
        """Capture a screenshot and return its path."""
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        filename = f"{self.name}_{label}_{timestamp}.png"
        filepath = str(SCREENSHOT_DIR / filename)
        try:
            await page.screenshot(path=filepath)
            logger.info(f"Screenshot saved: {filepath}")
            return filepath
        except Exception as e:
            logger.warning(f"Screenshot failed: {e}")
            return ""

    async def validate(self, db_records: list[dict], max_records: int = 50) -> dict:
        """Run full validation cycle: launch browser, login, extract, compare.

        Args:
            db_records: Records from our database to validate against portal.
            max_records: Max records to check (portals may rate-limit).

        Returns:
            ValidationSummary as dict.
        """
        self.summary = ValidationSummary(self.name, self.portal_url)
        records_to_check = db_records[:max_records]

        try:
            from browser_use import Browser, BrowserConfig

            browser_config = BrowserConfig(headless=self.headless)
            self.browser = Browser(config=browser_config)
            context = await self.browser.new_context()
            self.page = await context.get_current_page()

            # Navigate to portal
            await self.page.goto(self.portal_url, wait_until="networkidle", timeout=30000)
            screenshot = await self._take_screenshot(self.page, "landing")
            if screenshot:
                self.summary.add_screenshot(screenshot)

            # Login
            username, password = self._get_credentials()
            if not username or not password:
                self.summary.add_error(
                    f"Missing credentials. Set environment variables for {self.name}."
                )
                self.summary.finalize("error")
                return self.summary.to_dict()

            login_ok = await self._login(self.page)
            if not login_ok:
                screenshot = await self._take_screenshot(self.page, "login_failed")
                if screenshot:
                    self.summary.add_screenshot(screenshot)
                self.summary.add_error("Login failed — check credentials or portal availability.")
                self.summary.finalize("error")
                return self.summary.to_dict()

            screenshot = await self._take_screenshot(self.page, "logged_in")
            if screenshot:
                self.summary.add_screenshot(screenshot)

            # Extract portal data
            portal_data = await self._extract_portal_data(self.page, records_to_check)

            # Compare
            portal_by_id = {str(p.get("record_id", "")): p for p in portal_data}
            for db_rec in records_to_check:
                rec_id = str(db_rec.get("record_id", db_rec.get("id", "")))
                portal_rec = portal_by_id.get(rec_id)
                if portal_rec:
                    results = self._compare(db_rec, portal_rec)
                    for r in results:
                        self.summary.add_result(r)
                else:
                    self.summary.add_result(ValidationResult(
                        record_id=rec_id,
                        field="existence",
                        db_value="present",
                        portal_value="not_found",
                        match=False,
                        notes="Record not found in portal",
                    ))

            screenshot = await self._take_screenshot(self.page, "complete")
            if screenshot:
                self.summary.add_screenshot(screenshot)
            self.summary.finalize("completed")

        except ImportError:
            self.summary.add_error(
                "browser-use not installed. Run: pip install browser-use"
            )
            self.summary.finalize("error")
        except Exception as e:
            logger.error(f"Validation error: {e}", exc_info=True)
            self.summary.add_error(str(e))
            self.summary.finalize("error")
        finally:
            if self.browser:
                try:
                    await self.browser.close()
                except Exception:
                    pass

        return self.summary.to_dict()


class ManualBrowserSession:
    """Launch a browser for manual login, then run automated validation.

    For portals with CAPTCHA or 2FA where automated login won't work.
    The user logs in manually, then we take over for data extraction.
    """

    def __init__(self, portal_url: str):
        self.portal_url = portal_url
        self.browser = None

    async def launch(self) -> dict:
        """Launch visible browser at portal URL. User logs in manually."""
        try:
            from browser_use import Browser, BrowserConfig

            self.browser = Browser(config=BrowserConfig(headless=False))
            context = await self.browser.new_context()
            page = await context.get_current_page()
            await page.goto(self.portal_url, wait_until="networkidle", timeout=30000)

            return {
                "status": "launched",
                "message": f"Browser opened at {self.portal_url}. "
                           "Log in manually, then call /api/browser/continue to run validation.",
                "portal_url": self.portal_url,
            }
        except Exception as e:
            return {"status": "error", "message": str(e)}

    async def close(self):
        if self.browser:
            await self.browser.close()
