"""API-key authentication (N8N-001 Part 1).

The public API (`/public/v1/*`) and webhook-subscription CRUD accept an API key
in addition to (or instead of) a JWT. A key is minted once, shown once, and
stored ONLY as a sha256 hash. This module resolves a presented key to its
workspace and arms Postgres RLS via ``set_request_workspace`` — the SAME final
step ``app.auth.get_current_workspace`` performs for a JWT, so a key-authed
request is scoped identically to a logged-in user.

Key format: ``omni_sk_<43 url-safe base64 chars>`` (32 random bytes). The stored
prefix is ``omni_sk_`` + the first 8 chars of the random part, shown in the UI so
a user can tell keys apart without ever seeing the secret again.

Lookup MUST run under ``system_scope()`` — it is resolving WHICH workspace the
request belongs to, so it cannot itself be workspace-scoped. The comparison is on
the sha256 hash (unique-indexed), which is already a constant-time-ish exact match
in the DB; we additionally use ``hmac.compare_digest`` on the retrieved hash as a
belt-and-braces constant-time guard.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import AuthContext, get_current_workspace
from app.db import execute, fetch_one, set_request_workspace, system_scope

log = logging.getLogger(__name__)

_KEY_PREFIX = "omni_sk_"
# auto_error=False so a missing/other-scheme header falls through to the JWT path.
_bearer = HTTPBearer(auto_error=False)


def generate_api_key() -> tuple[str, str, str]:
    """Mint a new key. Returns ``(raw_key, key_prefix, key_hash)``.

    Only ``key_prefix`` + ``key_hash`` are persisted; ``raw_key`` is returned to
    the caller ONCE and never stored."""
    random_part = secrets.token_urlsafe(32)
    raw_key = f"{_KEY_PREFIX}{random_part}"
    key_prefix = f"{_KEY_PREFIX}{random_part[:8]}"
    key_hash = hash_api_key(raw_key)
    return raw_key, key_prefix, key_hash


def hash_api_key(raw_key: str) -> str:
    """sha256 hex digest of the raw key. The ONLY form we persist/compare."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def _extract_api_key(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str | None:
    """Pull an ``omni_sk_`` key from ``Authorization: Bearer`` or ``X-API-Key``.

    Returns None when no API key is present (so the caller can fall back to JWT)."""
    if credentials and credentials.credentials and credentials.credentials.startswith(_KEY_PREFIX):
        return credentials.credentials
    header_key = request.headers.get("x-api-key")
    if header_key and header_key.startswith(_KEY_PREFIX):
        return header_key
    return None


async def _resolve_key_workspace(raw_key: str) -> AuthContext:
    """Resolve a raw API key to its workspace, arming RLS. Raises 401 on any miss."""
    key_hash = hash_api_key(raw_key)
    async with system_scope():
        row = await fetch_one(
            "SELECT id, workspace_id, key_hash, created_by, revoked_at "
            "FROM omni_api_keys WHERE key_hash = $1",
            key_hash,
        )
    if not row or row.get("revoked_at") is not None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    # Belt-and-braces constant-time compare against the stored hash.
    if not hmac.compare_digest(str(row["key_hash"]), key_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")

    workspace_id = str(row["workspace_id"])
    # Bump last_used_at best-effort — never block or fail the request on this.
    try:
        async with system_scope():
            await execute(
                "UPDATE omni_api_keys SET last_used_at = NOW() WHERE id = $1", row["id"]
            )
    except Exception:  # noqa: BLE001
        log.warning("failed to bump last_used_at for api key %s", row["id"])

    set_request_workspace(workspace_id)
    return AuthContext(user_id=str(row["created_by"]) if row.get("created_by") else "", workspace_id=workspace_id)


async def get_apikey_workspace(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthContext:
    """Resolve the request's API key to an ``AuthContext`` (arms RLS). 401 if none."""
    raw_key = _extract_api_key(request, credentials)
    if not raw_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key required")
    return await _resolve_key_workspace(raw_key)


async def get_workspace_any(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> AuthContext:
    """Accept EITHER an API key OR a JWT. Prefer the API key when an ``omni_sk_``
    is presented; otherwise fall through to the JWT/cookie path. Both end in
    ``set_request_workspace`` so RLS scoping is identical either way."""
    raw_key = _extract_api_key(request, credentials)
    if raw_key:
        return await _resolve_key_workspace(raw_key)
    return await get_current_workspace(request, credentials)
