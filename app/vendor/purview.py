"""Purview PACS image viewer / report download connector.

Downloads reports and study data from Purview's web portal.
OUTBOUND-ONLY — only your login credentials are sent to Purview.
No OCDR data is ever transmitted.

Requires: pip install playwright && playwright install chromium
"""
import os
import logging
from datetime import datetime, timedelta

from app.vendor.base_connector import BaseConnector

logger = logging.getLogger(__name__)

PURVIEW_LOGIN_URL = 'https://cloud.purview.net/'


class PurviewConnector(BaseConnector):
    """Download reports from Purview PACS portal."""

    VENDOR_NAME = 'purview'

    def __init__(self, download_dir=None, headless=True, portal_url=None):
        super().__init__(download_dir)
        self._browser = None
        self._page = None
        self._playwright = None
        self.headless = headless
        self.portal_url = portal_url or PURVIEW_LOGIN_URL

    def login(self, username, password, **kwargs):
        """Log into Purview portal."""
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

        logger.info(f'Navigating to Purview login...')
        self._page.goto(self.portal_url, wait_until='networkidle', timeout=30000)

        # Fill login form — Purview uses various form layouts
        try:
            self._page.fill('input[name="username"], input[type="email"], #username', username)
            self._page.fill('input[name="password"], input[type="password"], #password', password)
            self._page.click('button[type="submit"], input[type="submit"], #loginButton')
            self._page.wait_for_load_state('networkidle', timeout=15000)
        except Exception as e:
            logger.error(f'Login form interaction failed: {e}')
            return False

        # Check login success
        if 'login' in self._page.url.lower() or 'signin' in self._page.url.lower():
            logger.error('Purview login failed — still on login page.')
            return False

        self._authenticated = True
        logger.info('Purview login successful.')
        return True

    def download_files(self, date_from=None, date_to=None):
        """Download available reports/CSV exports from Purview."""
        if not self._authenticated:
            raise RuntimeError('Not logged in. Call login() first.')

        downloaded = []

        # Look for export/download links on the current page
        try:
            export_links = self._page.query_selector_all(
                'a[href*="export"], a[href*="download"], '
                'button:has-text("Export"), button:has-text("Download")'
            )

            for link in export_links:
                try:
                    with self._page.expect_download(timeout=30000) as download_info:
                        link.click()
                    download = download_info.value
                    filepath = os.path.join(self.download_dir, download.suggested_filename)
                    download.save_as(filepath)

                    # Determine file type from extension
                    ext = os.path.splitext(download.suggested_filename)[1].lower()
                    file_type_map = {
                        '.835': '835', '.edi': '835', '.csv': 'csv',
                        '.pdf': 'pdf', '.xlsx': 'excel', '.xls': 'excel',
                    }
                    file_type = file_type_map.get(ext, 'unknown')

                    downloaded.append({
                        'filename': download.suggested_filename,
                        'filepath': filepath,
                        'file_type': file_type,
                        'size': os.path.getsize(filepath),
                    })
                    logger.info(f'Downloaded: {download.suggested_filename}')
                except Exception as e:
                    logger.warning(f'Failed to download: {e}')
        except Exception as e:
            logger.error(f'Error finding download links: {e}')

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
