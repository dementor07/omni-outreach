"""Generic OAuth-token storage + refresh helpers.

Stores per-(provider, user_id) tokens in the ``oauth_tokens`` table
(migration 017). Tokens are encrypted at rest with the same Fernet key
the rest of the app uses.

Public surface:
  - ``store_token(provider, user_id, access_token, refresh_token=, ...)``
    upserts a row, encrypting both tokens.
  - ``get_access_token(provider, user_id, refresher=)`` returns a non-expired
    access_token, transparently calling the provider-specific ``refresher``
    if the stored access_token is within 60 seconds of expiry. Returns None
    if the user has no row, or if refresh fails.
  - ``get_latest_user_with_token(provider)`` for the system fallback when
    no specific user is in context (e.g. cron-driven lead-gen runs that
    don't carry a user_id today). Picks the most-recently-connected row.

Provider modules register their own refresher functions and call into
``store_token`` / ``get_access_token``; this module knows nothing about
specific providers.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

from app.db import execute, fetch_one
from app.services.encryption import decrypt, encrypt

log = logging.getLogger(__name__)


# Refresh ``access_token`` when within this many seconds of expiry so we
# don't race the clock on a slow Apollo call.
REFRESH_LEEWAY_SECONDS = 60


# A refresher callback. It receives the decrypted refresh_token and must
# return ``(new_access_token, new_refresh_token, new_expires_at, new_scope)``
# or raise. ``new_refresh_token`` may be the same as the input (PH rotates
# it; some providers don't).
RefreshCallback = Callable[
    [str],
    Awaitable[tuple[str, str | None, datetime | None, str | None]],
]


async def store_token(
    *,
    provider: str,
    user_id: str,
    access_token: str,
    refresh_token: str | None = None,
    expires_at: datetime | None = None,
    scope: str | None = None,
    remote_user_id: str | None = None,
    remote_username: str | None = None,
) -> None:
    """Upsert a token row for ``(provider, user_id)``.

    All token columns get re-encrypted on every write — if a refresh comes
    in we always have a fresh ciphertext."""
    await execute(
        """
        INSERT INTO oauth_tokens (
            provider, user_id, remote_user_id, remote_username,
            access_token_enc, refresh_token_enc, scope, expires_at,
            connected_at, last_refresh_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW(), NULL)
        ON CONFLICT (provider, user_id) DO UPDATE
        SET remote_user_id      = COALESCE(EXCLUDED.remote_user_id, oauth_tokens.remote_user_id),
            remote_username     = COALESCE(EXCLUDED.remote_username, oauth_tokens.remote_username),
            access_token_enc    = EXCLUDED.access_token_enc,
            refresh_token_enc   = COALESCE(EXCLUDED.refresh_token_enc, oauth_tokens.refresh_token_enc),
            scope               = COALESCE(EXCLUDED.scope, oauth_tokens.scope),
            expires_at          = EXCLUDED.expires_at,
            connected_at        = oauth_tokens.connected_at,
            last_refresh_at     = NULL
        """,
        provider,
        user_id,
        remote_user_id,
        remote_username,
        encrypt(access_token),
        encrypt(refresh_token) if refresh_token else None,
        scope,
        expires_at,
    )


async def get_access_token(
    *,
    provider: str,
    user_id: str,
    refresher: RefreshCallback | None = None,
) -> str | None:
    """Return a usable access_token, refreshing if needed.

    Returns ``None`` when:
      - the user has never authorized this provider, OR
      - refresh fails (the caller should treat this as "needs reauth")
    """
    row = await fetch_one(
        """
        SELECT access_token_enc, refresh_token_enc, expires_at
        FROM oauth_tokens WHERE provider=$1 AND user_id=$2
        """,
        provider,
        user_id,
    )
    if not row:
        return None

    expires_at = row.get("expires_at")
    now = datetime.now(UTC)
    needs_refresh = bool(
        expires_at and expires_at <= now + timedelta(seconds=REFRESH_LEEWAY_SECONDS)
    )

    if not needs_refresh:
        try:
            return decrypt(row["access_token_enc"])
        except Exception as e:  # noqa: BLE001
            log.error("[oauth_tokens] %s decrypt failed for user=%s: %s", provider, user_id, e)
            return None

    if not refresher:
        log.warning(
            "[oauth_tokens] %s token for user=%s expired but no refresher supplied",
            provider, user_id,
        )
        return None

    if not row.get("refresh_token_enc"):
        log.warning(
            "[oauth_tokens] %s token for user=%s expired and has no refresh_token stored",
            provider, user_id,
        )
        return None

    try:
        refresh_token = decrypt(row["refresh_token_enc"])
    except Exception as e:  # noqa: BLE001
        log.error("[oauth_tokens] %s refresh-decrypt failed for user=%s: %s", provider, user_id, e)
        return None

    try:
        new_access, new_refresh, new_exp, new_scope = await refresher(refresh_token)
    except Exception as e:  # noqa: BLE001
        log.error("[oauth_tokens] %s refresh failed for user=%s: %s", provider, user_id, e)
        return None

    # Persist refreshed values. last_refresh_at gets set explicitly here
    # rather than via the upsert path so we have a clean audit signal.
    await execute(
        """
        UPDATE oauth_tokens
           SET access_token_enc  = $1,
               refresh_token_enc = COALESCE($2, refresh_token_enc),
               expires_at        = $3,
               scope             = COALESCE($4, scope),
               last_refresh_at   = NOW()
         WHERE provider=$5 AND user_id=$6
        """,
        encrypt(new_access),
        encrypt(new_refresh) if new_refresh else None,
        new_exp,
        new_scope,
        provider,
        user_id,
    )
    return new_access


async def get_latest_user_with_token(provider: str) -> str | None:
    """Fallback selector for cron-driven jobs that don't carry a user_id.

    Picks the most-recently-connected operator who has a row for this
    provider. Good enough until campaigns get an owner_user_id column."""
    row = await fetch_one(
        """
        SELECT user_id FROM oauth_tokens
        WHERE provider=$1
        ORDER BY connected_at DESC
        LIMIT 1
        """,
        provider,
    )
    return str(row["user_id"]) if row else None


async def disconnect(provider: str, user_id: str) -> None:
    await execute(
        "DELETE FROM oauth_tokens WHERE provider=$1 AND user_id=$2",
        provider,
        user_id,
    )


async def status(provider: str, user_id: str) -> dict | None:
    row = await fetch_one(
        """
        SELECT remote_username, remote_user_id, scope, expires_at,
               connected_at, last_refresh_at
        FROM oauth_tokens WHERE provider=$1 AND user_id=$2
        """,
        provider,
        user_id,
    )
    if not row:
        return None
    return {
        "connected": True,
        "remote_username": row["remote_username"],
        "remote_user_id": row["remote_user_id"],
        "scope": row["scope"],
        "expires_at": row["expires_at"].isoformat() if row["expires_at"] else None,
        "connected_at": row["connected_at"].isoformat() if row["connected_at"] else None,
        "last_refresh_at": row["last_refresh_at"].isoformat() if row["last_refresh_at"] else None,
    }
