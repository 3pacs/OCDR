"""Purview (Ambra Health / Intelerad) PACS connector.

Downloads study data, reports, and patient metadata from Purview's web portal.
OUTBOUND-ONLY — only your login credentials are sent to Purview.
No OCDR data is ever transmitted.

Purview is a cloud-based medical image management platform.
The user's portal is at https://image-us-east1.purview.net/login

Requires: pip install playwright && playwright install chromium
"""
import os
import csv
import json
import logging
from datetime import datetime, timedelta

from app.vendor.base_connector import BaseConnector

logger = logging.getLogger(__name__)

DEFAULT_PURVIEW_URL = 'https://image-us-east1.purview.net/login'


class PurviewConnector(BaseConnector):
    """Download study data and reports from Purview PACS portal."""

    VENDOR_NAME = 'purview'
    DOWNLOAD_EXTENSIONS = ('.csv', '.xlsx', '.xls', '.pdf', '.txt')

    def __init__(self, download_dir=None, headless=True, portal_url=None):
        super().__init__(download_dir)
        self._browser = None
        self._page = None
        self._playwright = None
        self.headless = headless
        self.portal_url = portal_url or DEFAULT_PURVIEW_URL

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

        portal_url = kwargs.get('portal_url') or self.portal_url

        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(
            headless=self.headless,
            downloads_path=self.download_dir,
            args=[
                '--ignore-certificate-errors',
            ],
        )
        context = self._browser.new_context(ignore_https_errors=True)
        self._page = context.new_page()

        logger.info(f'Navigating to Purview login at {portal_url}...')
        try:
            self._page.goto(portal_url, wait_until='networkidle', timeout=30000)
        except Exception as e:
            if 'timeout' in str(e).lower():
                logger.warning('Purview networkidle timed out, retrying with domcontentloaded...')
                self._page.goto(portal_url, wait_until='domcontentloaded', timeout=30000)
            else:
                raise

        # Purview (Ambra Health) is a React SPA — the login form renders
        # after JavaScript execution.  Wait for a password field to appear
        # as a reliable signal that the form has mounted.
        try:
            self._page.wait_for_selector(
                'input[type="password"]', state='visible', timeout=15000
            )
        except Exception:
            logger.warning('Purview: password field did not appear within 15s, proceeding anyway')

        # Purview / Ambra Health uses "login" as the field name, not "username".
        # Include both Ambra-specific and generic selectors.
        username_selectors = [
            # Ambra Health / Purview specific
            'input[name="login"]',
            'input[name="signin"]',
            'input[id="login"]',
            'input[id="signin"]',
            # Generic selectors
            'input[name="username"]',
            'input[name="email"]',
            'input[type="email"]',
            '#username',
            '#email',
            'input[placeholder*="username" i]',
            'input[placeholder*="email" i]',
            'input[placeholder*="login" i]',
            # Last resort: first visible text input that is not password
            'input[type="text"]:not([type="password"])',
        ]

        password_selectors = [
            'input[name="password"]',
            'input[type="password"]',
            '#password',
        ]

        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            '#loginButton',
            'button:has-text("Log In")',
            'button:has-text("Login")',
            'button:has-text("Sign In")',
            'button:has-text("Sign in")',
            # Ambra-specific
            'button.btn-primary',
        ]

        try:
            # Fill username
            filled_user = False
            for sel in username_selectors:
                try:
                    el = self._page.query_selector(sel)
                    if el and el.is_visible():
                        el.fill(username)
                        filled_user = True
                        logger.info(f'Filled username via {sel}')
                        break
                except Exception:
                    continue

            if not filled_user:
                self._log_page_debug_info('username')
                self._last_login_error = 'Purview login: could not find username field'
                logger.error(self._last_login_error)
                return False

            # Fill password
            filled_pass = False
            for sel in password_selectors:
                try:
                    el = self._page.query_selector(sel)
                    if el and el.is_visible():
                        el.fill(password)
                        filled_pass = True
                        logger.info(f'Filled password via {sel}')
                        break
                except Exception:
                    continue

            if not filled_pass:
                self._log_page_debug_info('password')
                self._last_login_error = 'Purview login: could not find password field'
                logger.error(self._last_login_error)
                return False

            # Submit
            submitted = False
            for sel in submit_selectors:
                try:
                    el = self._page.query_selector(sel)
                    if el and el.is_visible():
                        el.click()
                        submitted = True
                        logger.info(f'Clicked submit via {sel}')
                        break
                except Exception:
                    continue

            if not submitted:
                self._page.keyboard.press('Enter')

            self._page.wait_for_load_state('networkidle', timeout=15000)

        except Exception as e:
            self._last_login_error = f'Purview login form error: {e}'
            logger.error(self._last_login_error)
            return False

        # Check login success
        current_url = self._page.url.lower()
        if 'login' in current_url or 'signin' in current_url:
            # Grab page text for diagnostics (error banners, etc.)
            error_text = ''
            for sel in ['.error', '.alert-danger', '.login-error', '[role="alert"]',
                        '.error-message', '.form-error', '.text-danger']:
                try:
                    el = self._page.query_selector(sel)
                    if el:
                        error_text = el.inner_text().strip()
                        break
                except Exception:
                    continue
            if error_text:
                self._last_login_error = f'Purview login rejected: {error_text}'
            else:
                self._last_login_error = (
                    'Purview login failed — wrong credentials, MFA required, or IP restriction'
                )
            logger.error(self._last_login_error)
            return False

        self._authenticated = True
        logger.info('Purview login successful.')
        return True

    def _log_page_debug_info(self, field_type):
        """Log page state for debugging when selectors fail."""
        try:
            url = self._page.url
            title = self._page.title()
            # Count visible input elements
            inputs = self._page.query_selector_all('input')
            visible_inputs = []
            for inp in inputs:
                try:
                    if inp.is_visible():
                        attrs = {}
                        for attr in ['type', 'name', 'id', 'placeholder', 'class']:
                            val = inp.get_attribute(attr)
                            if val:
                                attrs[attr] = val
                        visible_inputs.append(attrs)
                except Exception:
                    continue
            logger.error(
                f'Purview debug ({field_type} not found): '
                f'url={url}, title={title}, '
                f'visible_inputs={json.dumps(visible_inputs)}'
            )
            # Also log a snippet of the page HTML for further diagnosis
            body_html = self._page.inner_html('body')
            if body_html:
                logger.debug(f'Purview page body (first 2000 chars): {body_html[:2000]}')
        except Exception as e:
            logger.error(f'Purview debug info collection failed: {e}')

    def download_files(self, date_from=None, date_to=None):
        """Download available reports and study data from Purview.

        Tries multiple strategies:
        1. Use built-in export/download buttons
        2. Scrape the study list table
        3. Navigate to reports section
        """
        if not self._authenticated:
            raise RuntimeError('Not logged in. Call login() first.')

        if date_from is None:
            date_from = '01/01/2000'
        if date_to is None:
            date_to = datetime.now().strftime('%m/%d/%Y')

        downloaded = []

        # Strategy 1: Look for export/download links on current page
        downloaded.extend(self._try_page_exports())

        # Strategy 2: Scrape study list
        downloaded.extend(self._try_scrape_study_list(date_from, date_to))

        # Strategy 3: Navigate to reports section
        downloaded.extend(self._try_reports_section(date_from, date_to))

        return downloaded

    def _try_page_exports(self):
        """Look for export/download buttons on current page."""
        downloaded = []

        export_selectors = [
            'a[href*="export" i]',
            'a[href*="download" i]',
            'button:has-text("Export")',
            'button:has-text("Download")',
            'button:has-text("CSV")',
            'a:has-text("Export")',
            'a:has-text("Download")',
        ]

        for sel in export_selectors:
            try:
                elements = self._page.query_selector_all(sel)
                for el in elements:
                    if not el.is_visible():
                        continue
                    try:
                        with self._page.expect_download(timeout=30000) as download_info:
                            el.click()
                        download = download_info.value
                        filepath = os.path.join(
                            self.download_dir, download.suggested_filename
                        )
                        download.save_as(filepath)

                        ext = os.path.splitext(download.suggested_filename)[1].lower()
                        file_type_map = {
                            '.csv': 'csv', '.xlsx': 'excel', '.xls': 'excel',
                            '.pdf': 'pdf', '.835': '835', '.edi': '835',
                        }

                        downloaded.append({
                            'filename': download.suggested_filename,
                            'filepath': filepath,
                            'file_type': file_type_map.get(ext, 'unknown'),
                            'size': os.path.getsize(filepath),
                            'source': 'purview_export',
                        })
                        logger.info(f'Downloaded: {download.suggested_filename}')
                    except Exception as e:
                        logger.debug(f'Download from {sel} failed: {e}')
            except Exception:
                continue

        return downloaded

    def _try_scrape_study_list(self, date_from, date_to):
        """Scrape the study list table from Purview."""
        downloaded = []

        # Purview typically shows a study list with patient info
        study_nav = [
            'a:has-text("Studies")',
            'a:has-text("Study List")',
            'a:has-text("Worklist")',
            'a[href*="study" i]',
            'a[href*="worklist" i]',
        ]

        for sel in study_nav:
            try:
                el = self._page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    self._page.wait_for_load_state('networkidle', timeout=10000)
                    break
            except Exception:
                continue

        # Try to set date filters
        self._try_set_date_range(date_from, date_to)

        # Scrape the table
        rows = self._scrape_table_data()
        if rows:
            filename = f'purview_studies_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
            filepath = self._save_scraped_csv(rows, filename)
            if filepath:
                downloaded.append({
                    'filename': filename,
                    'filepath': filepath,
                    'file_type': 'csv',
                    'data_type': 'studies',
                    'size': os.path.getsize(filepath),
                    'source': 'purview_scrape',
                    'rows': len(rows),
                })
                logger.info(f'Scraped {len(rows)} study rows from Purview')

        return downloaded

    def _try_reports_section(self, date_from, date_to):
        """Navigate to reports section and download available reports."""
        downloaded = []

        report_nav = [
            'a:has-text("Reports")',
            'a:has-text("Analytics")',
            'a[href*="report" i]',
            'a[href*="analytics" i]',
        ]

        for sel in report_nav:
            try:
                el = self._page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    self._page.wait_for_load_state('networkidle', timeout=10000)

                    # Look for downloadable reports
                    files = self._try_page_exports()
                    downloaded.extend(files)

                    self._page.go_back()
                    self._page.wait_for_load_state('networkidle', timeout=5000)
                    break
            except Exception:
                continue

        return downloaded

    def _try_set_date_range(self, date_from, date_to):
        """Try to set date filter fields on current page."""
        date_from_selectors = [
            'input[name*="from" i]', 'input[name*="start" i]',
            'input[id*="from" i]', 'input[id*="start" i]',
            'input[type="date"]:first-of-type',
            'input[placeholder*="from" i]',
            'input[placeholder*="start" i]',
        ]
        date_to_selectors = [
            'input[name*="to" i]', 'input[name*="end" i]',
            'input[id*="to" i]', 'input[id*="end" i]',
            'input[type="date"]:last-of-type',
            'input[placeholder*="to" i]',
            'input[placeholder*="end" i]',
        ]
        search_selectors = [
            'button:has-text("Search")', 'button:has-text("Go")',
            'button:has-text("Filter")', 'button:has-text("Apply")',
            'button[type="submit"]', 'input[type="submit"]',
        ]

        for sel in date_from_selectors:
            try:
                el = self._page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(date_from)
                    break
            except Exception:
                continue

        for sel in date_to_selectors:
            try:
                el = self._page.query_selector(sel)
                if el and el.is_visible():
                    el.fill(date_to)
                    break
            except Exception:
                continue

        for sel in search_selectors:
            try:
                el = self._page.query_selector(sel)
                if el and el.is_visible():
                    el.click()
                    self._page.wait_for_load_state('networkidle', timeout=10000)
                    break
            except Exception:
                continue

    def _scrape_table_data(self):
        """Scrape data from HTML tables on current page with pagination."""
        all_rows = []
        max_pages = 200

        for _ in range(max_pages):
            tables = self._page.query_selector_all('table')
            for table in tables:
                try:
                    headers = []
                    th_elements = table.query_selector_all('thead th, tr:first-child th')
                    if not th_elements:
                        th_elements = table.query_selector_all('tr:first-child td')
                    headers = [th.inner_text().strip() for th in th_elements]

                    if not headers or len(headers) < 2:
                        continue

                    body_rows = table.query_selector_all('tbody tr')
                    if not body_rows:
                        body_rows = table.query_selector_all('tr')[1:]

                    for tr in body_rows:
                        cells = tr.query_selector_all('td')
                        if len(cells) != len(headers):
                            continue
                        row = {}
                        for i, cell in enumerate(cells):
                            row[headers[i]] = cell.inner_text().strip()
                        if any(v for v in row.values()):
                            all_rows.append(row)
                except Exception:
                    continue

            # Pagination
            next_btn = None
            for sel in [
                'a:has-text("Next")', 'button:has-text("Next")',
                '.pagination .next a', 'a.next',
            ]:
                try:
                    el = self._page.query_selector(sel)
                    if el and el.is_visible() and el.is_enabled():
                        next_btn = el
                        break
                except Exception:
                    continue

            if next_btn:
                try:
                    next_btn.click()
                    self._page.wait_for_load_state('networkidle', timeout=10000)
                except Exception:
                    break
            else:
                break

        return all_rows

    def _save_scraped_csv(self, rows, filename):
        """Save scraped table data as CSV."""
        if not rows:
            return None

        filepath = os.path.join(self.download_dir, filename)
        headers = list(rows[0].keys())

        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            writer.writerows(rows)

        return filepath

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
