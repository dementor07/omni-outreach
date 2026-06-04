"""Encrypted integration key storage.

Uses Fernet symmetric encryption derived from SECRET_KEY.
Keys are encrypted at rest in the integration_keys table,
decrypted in-memory only when needed, and masked in API responses.
"""

import base64
import hashlib
import logging

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.config import settings

log = logging.getLogger(__name__)


def _hkdf_key(secret: str) -> bytes:
    """ENC-001: derive the Fernet key with HKDF-SHA256 (domain-separated by an
    ``info`` label) instead of a single unsalted SHA-256 pass. HKDF is the
    correct KDF for turning a high-entropy secret into a fixed-length key and
    the ``info`` tag scopes this key to connection encryption so the same
    SECRET_KEY can derive other independent keys later without collision."""
    raw = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"omni-connection-encryption",
    ).derive(secret.encode())
    return base64.urlsafe_b64encode(raw)


def _legacy_key(secret: str) -> bytes:
    """The original derivation: a single unsalted SHA-256 of SECRET_KEY. Kept as
    a decrypt-only fallback so ciphertext written before the HKDF switch still
    decrypts. New writes always use the HKDF key (it is first in the
    MultiFernet). Re-encrypting old rows on next write rotates them forward."""
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


# Encrypt with HKDF (primary); decrypt with HKDF then legacy. MultiFernet tries
# keys in order, so existing SHA-256 ciphertext keeps decrypting during the
# migration window without a hard re-encrypt step.
_fernet = MultiFernet([Fernet(_hkdf_key(settings.secret_key)), Fernet(_legacy_key(settings.secret_key))])


def encrypt(plaintext: str) -> str:
    """Encrypt a plaintext string. Returns base64 token (HKDF-keyed)."""
    return _fernet.encrypt(plaintext.encode()).decode()


def decrypt(token: str) -> str:
    """Decrypt an encrypted token back to plaintext (HKDF, then legacy key)."""
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
