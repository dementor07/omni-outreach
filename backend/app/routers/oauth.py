"""Google OAuth2 flow for the Sheets lead source.

Three endpoints:
- POST /oauth/google/start    → returns a Google authorization URL (state CSRF token)
- GET  /oauth/google/callback → Google redirects here with code+state; we exchange,
                                 fetch the user's email, store the refresh_token
                                 encrypted, and redirect back to /lead-sources.
- GET  /oauth/google/status   → returns whether the current user has a connected
                                 Google account (and which email).
- DELETE /oauth/google         → disconnect; deletes the stored refresh_token.

Scope is locked to spreadsheets.readonly + openid email (so we can show
which account is connected). Access tokens are short-lived; we refresh on
demand inside ``get_access_token``.
"""

from __future__ import annotations

import logging
import secrets
import time
import urllib.parse

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import RedirectResponse

from app.auth import get_current_user
from app.config import settings
from app.db import execute, fetch_one
from app.services.encryption import decrypt, encrypt

log = logging.getLogger(__name__)

router = APIRouter()


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"
SCOPE = "https://www.googleapis.com/auth/spreadsheets.readonly openid email"

# In-memory state store: state_token -> (user_id, expires_at).
# This is a single-process backend so a dict is fine; if we scale horizontally
# we'd need Redis here. Tokens expire after 10 minutes.
_STATE_STORE: dict[str, tuple[str, float]] = {}
_STATE_TTL_SECONDS = 600


def _prune_state() -> None:
    now = time.time()
    expired = [k for k, (_, exp) in _STATE_STORE.items() if exp < now]
    for k in expired:
        _STATE_STORE.pop(k, None)


@router.post("/google/start")
async def start_flow(user_id: str = Depends(get_current_user)):
    """Return the Google authorization URL the frontend should open in a new tab."""
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise HTTPException(status_code=503, detail="Google OAuth is not configured on this server")

    _prune_state()
    state = secrets.token_urlsafe(32)
    _STATE_STORE[state] = (user_id, time.time() + _STATE_TTL_SECONDS)

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": settings.google_oauth_redirect_uri,
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",       # forces refresh_token issuance
        "prompt": "consent",            # re-prompt so refresh_token is always returned
        "include_granted_scopes": "true",
        "state": state,
    }
    return {"authorize_url": f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"}


@router.get("/google/callback")
async def callback(request: Request, code: str = Query(""), state: str = Query(""), error: str = Query("")):
    """Google's redirect target. Exchanges the code, persists the refresh token,
    then bounces back to /lead-sources with a status query param."""
    # The frontend lives behind the same nginx; relative redirects land at
    # the right origin without us computing request.base_url.
    if error:
        log.warning(f"[oauth] Google returned error={error}")
        return RedirectResponse(url=f"/lead-sources?google_oauth=error&reason={urllib.parse.quote(error)}")

    _prune_state()
    entry = _STATE_STORE.pop(state, None)
    if not entry:
        return RedirectResponse(url="/lead-sources?google_oauth=error&reason=invalid_state")
    user_id, _ = entry

    if not code:
        return RedirectResponse(url="/lead-sources?google_oauth=error&reason=missing_code")

    # Exchange code → tokens
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            tok_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret,
                    "redirect_uri": settings.google_oauth_redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except Exception as e:  # noqa: BLE001
            log.exception(f"[oauth] token exchange failed: {e}")
            return RedirectResponse(url="/lead-sources?google_oauth=error&reason=token_exchange_failed")

    if tok_resp.status_code >= 400:
        log.error(f"[oauth] token exchange HTTP {tok_resp.status_code}: {tok_resp.text[:200]}")
        return RedirectResponse(url=f"/lead-sources?google_oauth=error&reason=token_http_{tok_resp.status_code}")

    tok = tok_resp.json()
    refresh_token = tok.get("refresh_token")
    access_token = tok.get("access_token")
    granted_scopes = tok.get("scope", SCOPE)

    if not refresh_token:
        # Refresh tokens are only issued on the first consent. If the user
        # connected before and we lost the token, ask them to revoke + reconnect.
        log.warning("[oauth] no refresh_token in token response — user must revoke + reconnect")
        return RedirectResponse(url="/lead-sources?google_oauth=error&reason=no_refresh_token")

    # Fetch email for display
    google_email = None
    if access_token:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                ui = await client.get(
                    GOOGLE_USERINFO_URL,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
                if ui.status_code < 400:
                    google_email = ui.json().get("email")
            except Exception as e:  # noqa: BLE001
                log.warning(f"[oauth] userinfo lookup failed: {e}")

    # Persist (upsert on user_id)
    await execute(
        """
        INSERT INTO google_oauth_tokens (user_id, google_email, refresh_token_encrypted, scopes, connected_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (user_id) DO UPDATE
          SET google_email             = EXCLUDED.google_email,
              refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
              scopes                   = EXCLUDED.scopes,
              connected_at             = NOW(),
              last_refresh_at          = NULL
        """,
        user_id,
        google_email,
        encrypt(refresh_token),
        granted_scopes,
    )
    log.info(f"[oauth] stored refresh_token for user={user_id} email={google_email}")
    return RedirectResponse(url="/lead-sources?google_oauth=connected")


@router.get("/google/status")
async def status(user_id: str = Depends(get_current_user)):
    row = await fetch_one(
        "SELECT google_email, connected_at, scopes FROM google_oauth_tokens WHERE user_id=$1",
        user_id,
    )
    if not row:
        return {"connected": False}
    return {
        "connected": True,
        "google_email": row["google_email"],
        "connected_at": row["connected_at"].isoformat() if row["connected_at"] else None,
        "scopes": row["scopes"],
    }


@router.delete("/google")
async def disconnect(user_id: str = Depends(get_current_user)):
    await execute("DELETE FROM google_oauth_tokens WHERE user_id=$1", user_id)
    return {"status": "disconnected"}


# --- Helper used by GoogleSheetsSource -----------------------------------


async def get_access_token(user_id: str) -> str | None:
    """Return a fresh access token for this user, refreshing if needed.

    Returns None if the user has not connected Google or the refresh fails.
    """
    row = await fetch_one(
        "SELECT refresh_token_encrypted FROM google_oauth_tokens WHERE user_id=$1",
        user_id,
    )
    if not row:
        return None

    try:
        refresh_token = decrypt(row["refresh_token_encrypted"])
    except Exception as e:  # noqa: BLE001
        log.error(f"[oauth] failed to decrypt refresh_token for user={user_id}: {e}")
        return None

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret,
                    "refresh_token": refresh_token,
                    "grant_type": "refresh_token",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except Exception as e:  # noqa: BLE001
            log.error(f"[oauth] refresh request failed: {e}")
            return None

    if resp.status_code >= 400:
        log.error(f"[oauth] refresh HTTP {resp.status_code}: {resp.text[:200]}")
        return None
    access_token = resp.json().get("access_token")
    if access_token:
        await execute(
            "UPDATE google_oauth_tokens SET last_refresh_at=NOW() WHERE user_id=$1",
            user_id,
        )
    return access_token
