"""Encrypted credential storage for vendor portal logins.

Credentials are encrypted at rest using Fernet symmetric encryption.
The encryption key is derived from a master password using PBKDF2.
All data stays local — nothing is transmitted.

Usage:
    store = CredentialStore('/path/to/credentials.enc')
    store.unlock('master-password')
    store.set('officeally', 'username', 'mypassword')
    creds = store.get('officeally')  # {'username': ..., 'password': ...}
    store.save()
"""
import base64
import hashlib
import json
import os

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes


class CredentialStore:
    """Encrypted local credential storage using Fernet."""

    def __init__(self, filepath=None):
        if filepath is None:
            filepath = os.path.join(os.getcwd(), '.credentials.enc')
        self.filepath = filepath
        self._fernet = None
        self._data = {}
        self._salt = None

    def _derive_key(self, password, salt):
        """Derive a Fernet key from password + salt via PBKDF2."""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=480_000,
        )
        return base64.urlsafe_b64encode(kdf.derive(password.encode()))

    def unlock(self, master_password):
        """Unlock the credential store with the master password.

        Creates a new store if the file doesn't exist.
        """
        if os.path.exists(self.filepath):
            with open(self.filepath, 'rb') as f:
                raw = f.read()
            if len(raw) < 17:
                raise ValueError('Credential store file is corrupted')
            # First 16 bytes are the salt
            self._salt = raw[:16]
            encrypted = raw[16:]
            key = self._derive_key(master_password, self._salt)
            self._fernet = Fernet(key)
            try:
                decrypted = self._fernet.decrypt(encrypted)
            except InvalidToken:
                self._fernet = None
                raise ValueError('Wrong master password')
            self._data = json.loads(decrypted)
        else:
            # New store
            self._salt = os.urandom(16)
            key = self._derive_key(master_password, self._salt)
            self._fernet = Fernet(key)
            self._data = {}

    def save(self):
        """Write encrypted credentials to disk."""
        if self._fernet is None:
            raise RuntimeError('Store is locked. Call unlock() first.')
        plaintext = json.dumps(self._data).encode()
        encrypted = self._fernet.encrypt(plaintext)
        with open(self.filepath, 'wb') as f:
            f.write(self._salt + encrypted)
        # Restrict file permissions (owner-only on Unix)
        try:
            os.chmod(self.filepath, 0o600)
        except OSError:
            pass

    def set(self, vendor_name, username, password, extra=None):
        """Store credentials for a vendor."""
        if self._fernet is None:
            raise RuntimeError('Store is locked. Call unlock() first.')
        entry = {'username': username, 'password': password}
        if extra:
            entry['extra'] = extra
        self._data[vendor_name] = entry

    def get(self, vendor_name):
        """Retrieve credentials for a vendor. Returns None if not found."""
        if self._fernet is None:
            raise RuntimeError('Store is locked. Call unlock() first.')
        return self._data.get(vendor_name)

    def list_vendors(self):
        """List all stored vendor names (no secrets exposed)."""
        if self._fernet is None:
            raise RuntimeError('Store is locked. Call unlock() first.')
        return [
            {'vendor': k, 'username': v.get('username', '')}
            for k, v in self._data.items()
        ]

    def delete(self, vendor_name):
        """Remove credentials for a vendor."""
        if self._fernet is None:
            raise RuntimeError('Store is locked. Call unlock() first.')
        self._data.pop(vendor_name, None)
