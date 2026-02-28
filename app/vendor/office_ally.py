"""OfficeAlly ERA download connector.

Downloads 835 ERA files from OfficeAlly's provider portal.
OUTBOUND-ONLY — only your login credentials are sent to OfficeAlly.
No OCDR data is ever transmitted.

Requires: pip install playwright && playwright install chromium
"""
import os
import logging
from datetime import datetime, timedelta

from app.vendor.base_connector import BaseConnector

logger = logging.getLogger(__name__)

# OfficeAlly URLs (these are their public portal URLs)
OA_LOGIN_URL = 'https://pm.officeally.com/pm/login.aspx'
OA_ERA_URL = 'https://pm.officeally.com/pm/ERAListing.aspx'


class OfficeAllyConnector(BaseConnector):
    """Download 835 ERA files from OfficeAlly portal."""

    VENDOR_NAME = 'officeally'

    def __init__(self, download_dir=None, headless=True):
        super().__init__(download_dir)
        self._browser = None
        self._page = None
        self._playwright = None
        self.headless = headless

    def login(self, username, password, **kwargs):
        """Log into OfficeAlly provider portal."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise RuntimeError(
                'Playwright is not installed. Run:\n'
                '  pip install playwright\n'
                '  playwright install chromium'
            )

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            downloads_path=self.download_dir,
        )
        self._page = self._browser.new_page()

        logger.info(f'Navigating to OfficeAlly login...')
        self._page.goto(OA_LOGIN_URL, wait_until='networkidle', timeout=30000)

        # Fill login form
        self._page.fill('#txtUserName', username)
        self._page.fill('#txtPassword', password)
        self._page.click('#btnLogin')

        # Wait for navigation after login
        try:
            self._page.wait_for_load_state('networkidle', timeout=15000)
        except Exception:
            pass

        # Check if login succeeded (look for ERA menu or error message)
        if 'login' in self._page.url.lower():
            logger.error('OfficeAlly login failed — still on login page.')
            return False

        self._authenticated = True
        logger.info('OfficeAlly login successful.')
        return True

    def download_files(self, date_from=None, date_to=None):
        """Navigate to ERA listing and download available 835 files."""
        if not self._authenticated:
            raise RuntimeError('Not logged in. Call login() first.')

        if date_from is None:
            date_from = (datetime.now() - timedelta(days=30)).strftime('%m/%d/%Y')
        if date_to is None:
            date_to = datetime.now().strftime('%m/%d/%Y')

        logger.info(f'Navigating to ERA listing ({date_from} - {date_to})...')
        self._page.goto(OA_ERA_URL, wait_until='networkidle', timeout=30000)

        # Set date range if fields exist
        try:
            self._page.fill('#txtDateFrom', date_from)
            self._page.fill('#txtDateTo', date_to)
            self._page.click('#btnSearch')
            self._page.wait_for_load_state('networkidle', timeout=15000)
        except Exception as e:
            logger.warning(f'Could not set date range: {e}')

        # Find and click download links for 835 files
        downloaded = []
        download_links = self._page.query_selector_all('a[href*="835"], a[href*="ERA"], a[href*="download"]')

        for link in download_links:
            try:
                with self._page.expect_download(timeout=30000) as download_info:
                    link.click()
                download = download_info.value
                filepath = os.path.join(self.download_dir, download.suggested_filename)
                download.save_as(filepath)
                downloaded.append({
                    'filename': download.suggested_filename,
                    'filepath': filepath,
                    'file_type': '835',
                    'size': os.path.getsize(filepath),
                })
                logger.info(f'Downloaded: {download.suggested_filename}')
            except Exception as e:
                logger.warning(f'Failed to download: {e}')

        return downloaded

    def logout(self):
        """Close browser and clean up."""
        if self._page:
            try:
                self._page.close()
            except Exception:
                pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass
        if self._playwright:
            try:
                self._playwright.stop()
            except Exception:
                pass
        self._authenticated = False
