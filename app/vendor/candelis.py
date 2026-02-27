"""Candelis RadSuite RIS connector.

Downloads billing records and schedule data from the Candelis web portal.
OUTBOUND-ONLY — only your login credentials are sent to Candelis.
No OCDR data is ever transmitted.

Candelis RadSuite is a Radiology Information System accessed via web browser
on the local network (e.g., http://10.254.111.108).

Requires: pip install playwright && playwright install chromium
"""
import os
import csv
import json
import logging
import tempfile
from datetime import datetime, timedelta

from app.vendor.base_connector import BaseConnector

logger = logging.getLogger(__name__)


class CandelisConnector(BaseConnector):
    """Download billing and schedule data from Candelis RadSuite portal."""

    VENDOR_NAME = 'candelis'
    DOWNLOAD_EXTENSIONS = ('.csv', '.xlsx', '.xls', '.pdf', '.txt')

    def __init__(self, download_dir=None, headless=True, portal_url=None):
        super().__init__(download_dir)
        self._browser = None
        self._page = None
        self._playwright = None
        self.headless = headless
        self.portal_url = portal_url or 'http://10.254.111.108'

    def login(self, username, password, **kwargs):
        """Log into Candelis RadSuite portal."""
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
        )
        self._page = self._browser.new_page()

        logger.info(f'Navigating to Candelis login at {portal_url}...')
        self._page.goto(portal_url, wait_until='networkidle', timeout=30000)

        # Candelis RadSuite uses various login form layouts
        # Try common selectors for username/password fields
        username_selectors = [
            'input[name="username"]',
            'input[name="userName"]',
            'input[name="user"]',
            'input[name="login"]',
            'input[type="text"][id*="user" i]',
            'input[type="text"][id*="login" i]',
            'input[type="email"]',
            '#username',
            '#txtUsername',
            '#txtUser',
            '#UserName',
        ]

        password_selectors = [
            'input[name="password"]',
            'input[name="passwd"]',
            'input[type="password"]',
            '#password',
            '#txtPassword',
            '#Password',
        ]

        submit_selectors = [
            'button[type="submit"]',
            'input[type="submit"]',
            '#btnLogin',
            '#btnSubmit',
            'button:has-text("Log In")',
            'button:has-text("Login")',
            'button:has-text("Sign In")',
            'input[value="Login"]',
            'input[value="Log In"]',
        ]

        try:
            # Find and fill username
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
                logger.error('Could not find username field on Candelis login page')
                return False

            # Find and fill password
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
                logger.error('Could not find password field on Candelis login page')
                return False

            # Click submit
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
                # Try pressing Enter as fallback
                self._page.keyboard.press('Enter')

            self._page.wait_for_load_state('networkidle', timeout=15000)

        except Exception as e:
            logger.error(f'Candelis login form interaction failed: {e}')
            return False

        # Check login success — if still on login page, it failed
        current_url = self._page.url.lower()
        if 'login' in current_url or 'signin' in current_url or 'logon' in current_url:
            # Also check for error messages on the page
            error_text = self._page.query_selector('.error, .alert-danger, .login-error, #errorMsg')
            if error_text:
                logger.error(f'Candelis login failed: {error_text.inner_text()}')
            else:
                logger.error('Candelis login failed — still on login page.')
            return False

        self._authenticated = True
        logger.info('Candelis login successful.')
        return True

    def download_files(self, date_from=None, date_to=None):
        """Download billing and schedule data from Candelis.

        Navigates to reports/export sections and downloads available data.
        Returns list of downloaded file info dicts.
        """
        if not self._authenticated:
            raise RuntimeError('Not logged in. Call login() first.')

        if date_from is None:
            date_from = '01/01/2000'
        if date_to is None:
            date_to = datetime.now().strftime('%m/%d/%Y')

        downloaded = []

        # Try multiple approaches to find and download data
        # 1. Look for report/export sections in the navigation
        downloaded.extend(self._try_export_reports(date_from, date_to))

        # 2. Try to scrape billing data directly from tables
        downloaded.extend(self._try_scrape_billing(date_from, date_to))

        # 3. Try to scrape schedule data
        downloaded.extend(self._try_scrape_schedule(date_from, date_to))

        return downloaded

    def _try_export_reports(self, date_from, date_to):
        """Look for built-in export/report functionality."""
        downloaded = []

        # Common navigation patterns in Candelis RadSuite
        nav_patterns = [
            # Billing reports
            ('a[href*="report" i]', 'billing'),
            ('a[href*="billing" i]', 'billing'),
            ('a[href*="charge" i]', 'billing'),
            ('a[href*="claim" i]', 'billing'),
            ('a:has-text("Reports")', 'billing'),
            ('a:has-text("Billing")', 'billing'),
            # Schedule
            ('a[href*="schedule" i]', 'schedule'),
            ('a[href*="worklist" i]', 'schedule'),
            ('a:has-text("Schedule")', 'schedule'),
            # Export
            ('a[href*="export" i]', 'export'),
            ('button:has-text("Export")', 'export'),
        ]

        for selector, data_type in nav_patterns:
            try:
                link = self._page.query_selector(selector)
                if link and link.is_visible():
                    logger.info(f'Found {data_type} link: {selector}')
                    link.click()
                    self._page.wait_for_load_state('networkidle', timeout=10000)

                    # Look for export/download buttons on the resulting page
                    files = self._find_and_click_downloads(data_type)
                    downloaded.extend(files)

                    # Go back for next attempt
                    self._page.go_back()
                    self._page.wait_for_load_state('networkidle', timeout=5000)
            except Exception as e:
                logger.debug(f'Nav pattern {selector} failed: {e}')
                continue

        return downloaded

    def _find_and_click_downloads(self, data_type):
        """Find and click download/export buttons on current page."""
        downloaded = []

        export_selectors = [
            'a[href*="export" i]',
            'a[href*="download" i]',
            'a[href*=".csv" i]',
            'a[href*=".xlsx" i]',
            'button:has-text("Export")',
            'button:has-text("Download")',
            'button:has-text("CSV")',
            'button:has-text("Excel")',
            'input[value*="Export" i]',
            'input[value*="Download" i]',
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
                            'data_type': data_type,
                            'size': os.path.getsize(filepath),
                            'source': 'candelis_export',
                        })
                        logger.info(f'Downloaded: {download.suggested_filename}')
                    except Exception as e:
                        logger.debug(f'Download from {sel} failed: {e}')
            except Exception:
                continue

        return downloaded

    def _try_scrape_billing(self, date_from, date_to):
        """Try to scrape billing data directly from page tables."""
        downloaded = []

        # Try navigating to billing/charges section
        billing_urls = [
            '/billing', '/charges', '/claims',
            '/reports/billing', '/reports/charges',
            '/Billing', '/Charges', '/Claims',
        ]

        for path in billing_urls:
            try:
                url = self.portal_url.rstrip('/') + path
                self._page.goto(url, wait_until='networkidle', timeout=10000)

                # Check if page loaded (not 404 or redirect to login)
                if 'login' in self._page.url.lower():
                    continue

                # Try to set date range if date fields exist
                self._try_set_date_range(date_from, date_to)

                # Look for data tables
                rows = self._scrape_table_data()
                if rows:
                    filepath = self._save_scraped_csv(
                        rows, f'candelis_billing_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
                    )
                    downloaded.append({
                        'filename': os.path.basename(filepath),
                        'filepath': filepath,
                        'file_type': 'csv',
                        'data_type': 'billing',
                        'size': os.path.getsize(filepath),
                        'source': 'candelis_scrape',
                        'rows': len(rows),
                    })
                    logger.info(f'Scraped {len(rows)} billing rows from {path}')
            except Exception as e:
                logger.debug(f'Billing scrape from {path} failed: {e}')
                continue

        return downloaded

    def _try_scrape_schedule(self, date_from, date_to):
        """Try to scrape schedule data directly from page tables."""
        downloaded = []

        schedule_urls = [
            '/schedule', '/worklist', '/appointments',
            '/Schedule', '/Worklist', '/Appointments',
            '/reports/schedule',
        ]

        for path in schedule_urls:
            try:
                url = self.portal_url.rstrip('/') + path
                self._page.goto(url, wait_until='networkidle', timeout=10000)

                if 'login' in self._page.url.lower():
                    continue

                self._try_set_date_range(date_from, date_to)

                rows = self._scrape_table_data()
                if rows:
                    filepath = self._save_scraped_csv(
                        rows, f'candelis_schedule_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv'
                    )
                    downloaded.append({
                        'filename': os.path.basename(filepath),
                        'filepath': filepath,
                        'file_type': 'csv',
                        'data_type': 'schedule',
                        'size': os.path.getsize(filepath),
                        'source': 'candelis_scrape',
                        'rows': len(rows),
                    })
                    logger.info(f'Scraped {len(rows)} schedule rows from {path}')
            except Exception as e:
                logger.debug(f'Schedule scrape from {path} failed: {e}')
                continue

        return downloaded

    def _try_set_date_range(self, date_from, date_to):
        """Try to set date range fields if they exist on the page."""
        date_from_selectors = [
            'input[name*="from" i]', 'input[name*="start" i]',
            'input[id*="from" i]', 'input[id*="start" i]',
            'input[name*="dateFrom" i]', '#txtDateFrom',
            'input[type="date"]:first-of-type',
        ]
        date_to_selectors = [
            'input[name*="to" i]', 'input[name*="end" i]',
            'input[id*="to" i]', 'input[id*="end" i]',
            'input[name*="dateTo" i]', '#txtDateTo',
            'input[type="date"]:last-of-type',
        ]
        search_selectors = [
            'button:has-text("Search")', 'button:has-text("Go")',
            'button:has-text("Filter")', 'input[type="submit"]',
            'button[type="submit"]', '#btnSearch',
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
        """Scrape data from HTML tables on the current page.

        Handles pagination by looking for 'Next' buttons.
        Returns list of dicts (column_name -> value).
        """
        all_rows = []
        max_pages = 200  # Safety limit

        for _ in range(max_pages):
            tables = self._page.query_selector_all('table')
            for table in tables:
                try:
                    # Get headers
                    headers = []
                    th_elements = table.query_selector_all('thead th, tr:first-child th')
                    if not th_elements:
                        th_elements = table.query_selector_all('tr:first-child td')
                    headers = [th.inner_text().strip() for th in th_elements]

                    if not headers or len(headers) < 2:
                        continue

                    # Get data rows
                    body_rows = table.query_selector_all('tbody tr')
                    if not body_rows:
                        body_rows = table.query_selector_all('tr')[1:]  # Skip header row

                    for tr in body_rows:
                        cells = tr.query_selector_all('td')
                        if len(cells) != len(headers):
                            continue
                        row = {}
                        for i, cell in enumerate(cells):
                            row[headers[i]] = cell.inner_text().strip()
                        if any(v for v in row.values()):
                            all_rows.append(row)
                except Exception as e:
                    logger.debug(f'Table scrape error: {e}')
                    continue

            # Try pagination
            next_btn = None
            for sel in [
                'a:has-text("Next")', 'button:has-text("Next")',
                'a:has-text(">")', '.pagination .next a',
                'a.next', '#btnNext',
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
        """Save scraped table data as a CSV file."""
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
