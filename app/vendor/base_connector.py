"""Base class for vendor portal connectors.

All connectors are OUTBOUND-ONLY:
  - We connect TO vendor sites to download files
  - Vendors NEVER connect to us
  - No OCDR data is ever sent to vendors
  - Only login credentials (which you already use manually) are transmitted

Each connector implements:
  - login()    — authenticate with the vendor portal
  - download() — fetch available ERA/EOB/claim files
  - logout()   — clean up the session
"""
import os
import logging
from abc import ABC, abstractmethod
from datetime import datetime

logger = logging.getLogger(__name__)


class BaseConnector(ABC):
    """Base class for outbound-only vendor portal connectors."""

    VENDOR_NAME = 'unknown'
    DOWNLOAD_EXTENSIONS = ('.835', '.edi', '.csv', '.pdf', '.txt')

    def __init__(self, download_dir=None):
        if download_dir is None:
            download_dir = os.path.join(os.getcwd(), 'import', 'downloads')
        self.download_dir = download_dir
        os.makedirs(self.download_dir, exist_ok=True)
        self._authenticated = False

    @abstractmethod
    def login(self, username, password, **kwargs):
        """Authenticate with the vendor portal.

        Returns True on success, False on failure.
        Only login credentials are sent — no OCDR data.
        """
        pass

    @abstractmethod
    def download_files(self, date_from=None, date_to=None):
        """Download available files from the vendor portal.

        Returns a list of dicts:
          [{'filename': str, 'filepath': str, 'file_type': str, 'size': int}]

        Downloaded files are saved to self.download_dir.
        """
        pass

    @abstractmethod
    def logout(self):
        """Clean up the session."""
        pass

    def run(self, username, password, date_from=None, date_to=None, **kwargs):
        """Full download cycle: login → download → logout.

        Returns:
          {'vendor': str, 'files': list, 'errors': list}
        """
        errors = []
        files = []

        try:
            logger.info(f'[{self.VENDOR_NAME}] Logging in as {username}...')
            if not self.login(username, password, **kwargs):
                return {
                    'vendor': self.VENDOR_NAME,
                    'files': [],
                    'errors': ['Login failed'],
                }

            logger.info(f'[{self.VENDOR_NAME}] Downloading files...')
            files = self.download_files(date_from=date_from, date_to=date_to)
            logger.info(f'[{self.VENDOR_NAME}] Downloaded {len(files)} files.')

        except Exception as e:
            logger.error(f'[{self.VENDOR_NAME}] Error: {e}')
            errors.append(str(e))
        finally:
            try:
                self.logout()
            except Exception:
                pass

        return {
            'vendor': self.VENDOR_NAME,
            'files': files,
            'errors': errors,
            'timestamp': datetime.now().isoformat(),
        }

    def _save_file(self, filename, content):
        """Save downloaded content to the download directory.

        Returns the full file path.
        """
        # Sanitize filename
        safe_name = "".join(c for c in filename if c.isalnum() or c in '.-_ ')
        filepath = os.path.join(self.download_dir, safe_name)

        mode = 'wb' if isinstance(content, bytes) else 'w'
        with open(filepath, mode) as f:
            f.write(content)

        return filepath
