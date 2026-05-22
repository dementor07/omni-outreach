"""ProductHunt OAuth flow (authorization_code grant).

Endpoints (mounted at /api/oauth/producthunt):
  POST /start       → returns the PH authorize URL the frontend opens
  GET  /callback    → PH redirect target; exchanges code, stores tokens, bounces UI
  GET  /status      → "is this user connected" / metadata
  DELETE /          → disconnect

Auth model: per-operator. The currently-logged-in operator's token is what
the PH lead source uses for their own pulls. A cron-driven pull falls back
to ``get_latest_user_with_token('producthunt')``.

Scopes:
  public  — read posts, topics, comments. We always request this.
  private — read the authenticated user's own data. Not required for
            lead-gen so we don't ask for it (and asking would trigger a
            scarier consent screen).

Token expiry: PH access tokens last 60 days; refresh tokens are
re-issued on every refresh (we store the new one).
"""

from __future__ import annotations

import logging
import secrets
import time
import urllib.parse
from datetime import UTC, datetime, timedelta

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.auth import get_current_user
from app.config import settings
from app.services import oauth_tokens

log = logging.getLogger(__name__)

router = APIRouter()

PH_AUTHORIZE_URL = "https://api.producthunt.com/v2/oauth/authorize"
PH_TOKEN_URL = "https://api.producthunt.com/v2/oauth/token"
PH_GRAPHQL_URL = "https://api.producthunt.com/v2/api/graphql"
PROVIDER = "producthunt"
DEFAULT_SCOPE = "public"

# State store mirrors the Google router pattern — in-memory dict, 10min TTL.
# Single backend process today; move to Redis if we ever scale horizontally.
_STATE_STORE: dict[str, tuple[str, float]] = {}
_STATE_TTL_SECONDS = 600


def _prune_state() -> None:
    now = time.time()
    expired = [k for k, (_, exp) in _STATE_STORE.items() if exp < now]
    for k in expired:
        _STATE_STORE.pop(k, None)


def _ui_redirect(status: str, reason: str = "") -> RedirectResponse:
    """Bounce back to the UI lead-sources page with a status query param."""
    params = {"producthunt_oauth": status}
    if reason:
        params["reason"] = reason
    qs = urllib.parse.urlencode(params)
    return RedirectResponse(url=f"/lead-sources?{qs}")


def _redirect_uri() -> str:
    # The PH app's Redirect URI must exactly match this value.
    # Configurable via env so dev can point at localhost; defaults to prod.
    return (
        getattr(settings, "producthunt_oauth_redirect_uri", None)
        or "https://srv1575227.hstgr.cloud/api/oauth/producthunt/callback"
    )


def _client_creds() -> tuple[str, str] | None:
    key = (getattr(settings, "producthunt_api_key", "") or "").strip()
    secret = (getattr(settings, "producthunt_api_secret", "") or "").strip()
    if not key or not secret:
        return None
    return key, secret


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/start")
async def start_flow(user_id: str = Depends(get_current_user)) -> dict:
    creds = _client_creds()
    if not creds:
        raise HTTPException(503, "ProductHunt OAuth is not configured on this server")
    api_key, _ = creds

    _prune_state()
    state = secrets.token_urlsafe(32)
    _STATE_STORE[state] = (user_id, time.time() + _STATE_TTL_SECONDS)

    params = {
        "client_id": api_key,
        "redirect_uri": _redirect_uri(),
        "response_type": "code",
        "scope": DEFAULT_SCOPE,
        "state": state,
    }
    return {"authorize_url": f"{PH_AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"}


@router.get("/callback")
async def callback(
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
):
    if error:
        log.warning("[ph-oauth] PH returned error=%s", error)
        return _ui_redirect("error", error)

    _prune_state()
    entry = _STATE_STORE.pop(state, None)
    if not entry:
        return _ui_redirect("error", "invalid_state")
    user_id, _ = entry

    if not code:
        return _ui_redirect("error", "missing_code")

    creds = _client_creds()
    if not creds:
        return _ui_redirect("error", "server_misconfigured")
    api_key, api_secret = creds

    async with httpx.AsyncClient(timeout=15) as client:
        try:
            r = await client.post(
                PH_TOKEN_URL,
                json={
                    "client_id": api_key,
                    "client_secret": api_secret,
                    "redirect_uri": _redirect_uri(),
                    "code": code,
                    "grant_type": "authorization_code",
                },
            )
        except Exception as e:  # noqa: BLE001
            log.exception("[ph-oauth] token exchange failed: %s", e)
            return _ui_redirect("error", "token_exchange_failed")

    if r.status_code >= 400:
        log.error("[ph-oauth] token exchange HTTP %s: %s", r.status_code, r.text[:300])
        return _ui_redirect("error", f"token_http_{r.status_code}")

    tok = r.json() or {}
    access_token = tok.get("access_token")
    refresh_token = tok.get("refresh_token")
    scope = tok.get("scope") or DEFAULT_SCOPE
    expires_in = tok.get("expires_in")
    expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in))
        if expires_in
        else None
    )

    if not access_token:
        log.error("[ph-oauth] no access_token in response: %s", str(tok)[:200])
        return _ui_redirect("error", "no_access_token")

    # Resolve which PH user this is, for the connect-status UI.
    remote_user_id = None
    remote_username = None
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            who = await client.post(
                PH_GRAPHQL_URL,
                headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
                json={"query": "{ viewer { user { id name username } } }"},
            )
        if who.status_code < 400:
            viewer_user = (((who.json() or {}).get("data") or {}).get("viewer") or {}).get("user") or {}
            remote_user_id = viewer_user.get("id")
            remote_username = viewer_user.get("username") or viewer_user.get("name")
    except Exception as e:  # noqa: BLE001
        log.warning("[ph-oauth] viewer lookup failed (non-fatal): %s", e)

    await oauth_tokens.store_token(
        provider=PROVIDER,
        user_id=user_id,
        access_token=access_token,
        refresh_token=refresh_token,
        expires_at=expires_at,
        scope=scope,
        remote_user_id=remote_user_id,
        remote_username=remote_username,
    )
    log.info(
        "[ph-oauth] stored token for user=%s ph_user=%s scope=%s",
        user_id, remote_username, scope,
    )
    return _ui_redirect("connected")


@router.get("/status")
async def get_status(user_id: str = Depends(get_current_user)) -> dict:
    info = await oauth_tokens.status(PROVIDER, user_id)
    return info or {"connected": False}


@router.delete("")
async def disconnect(user_id: str = Depends(get_current_user)) -> dict:
    await oauth_tokens.disconnect(PROVIDER, user_id)
    return {"status": "disconnected"}


# ── Refresher used by the lead source ────────────────────────────────────────


async def _refresh(refresh_token: str) -> tuple[str, str | None, datetime | None, str | None]:
    """Trade a PH refresh_token for a new access_token.

    Used as the ``refresher`` callback passed to
    ``oauth_tokens.get_access_token``. Returns
    ``(access_token, refresh_token, expires_at, scope)``.
    """
    creds = _client_creds()
    if not creds:
        raise RuntimeError("PH OAuth client credentials missing")
    api_key, api_secret = creds

    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.post(
            PH_TOKEN_URL,
            json={
                "client_id": api_key,
                "client_secret": api_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
        )
    if r.status_code >= 400:
        raise RuntimeError(f"PH refresh HTTP {r.status_code}: {r.text[:200]}")
    tok = r.json() or {}
    new_access = tok.get("access_token")
    if not new_access:
        raise RuntimeError("PH refresh returned no access_token")
    new_refresh = tok.get("refresh_token")  # PH rotates refresh tokens
    expires_in = tok.get("expires_in")
    new_expires_at = (
        datetime.now(UTC) + timedelta(seconds=int(expires_in)) if expires_in else None
    )
    return new_access, new_refresh, new_expires_at, tok.get("scope")


async def resolve_user_access_token(preferred_user_id: str | None = None) -> str | None:
    """Public helper for the lead source.

    1. If ``preferred_user_id`` is supplied and has a stored token, use it.
    2. Otherwise pick the most-recently-connected operator with a PH token.
    3. Return None if no operator has authorized PH yet.
    """
    user_id = preferred_user_id or await oauth_tokens.get_latest_user_with_token(PROVIDER)
    if not user_id:
        return None
    return await oauth_tokens.get_access_token(
        provider=PROVIDER,
        user_id=user_id,
        refresher=_refresh,
    )
