"""Encrypted integration key storage.

Uses Fernet symmetric encryption derived from SECRET_KEY.
Keys are encrypted at rest in the integration_keys table,
decrypted in-memory only when needed, and masked in API responses.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings

log = logging.getLogger(__name__)

# Derive a Fernet key from SECRET_KEY using SHA-256 → base64
_raw = hashlib.sha256(settings.secret_key.encode()).digest()
_fernet = Fernet(base64.urlsafe_b64encode(_raw))


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns base64 token."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt an encrypted token back to plaintext."""
    try:
        return _fernet.decrypt(token.encode()).decode()
    except InvalidToken:
        log.error("Failed to decrypt integration key — token invalid or key rotated")
        raise ValueError("Decryption failed")


def mask(value: str) -> str:
    """Mask all but last 4 characters: ••••••••abc1"""
    if len(value) <= 4:
        return "••••"
    return "•" * min(len(value) - 4, 12) + value[-4:]
