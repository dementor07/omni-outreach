"""Google sign-in flow (authentication, not just Sheets data access).

Two endpoints, both unauthenticated:

  POST /auth/google/login    → returns Google authorize URL the frontend opens
  GET  /auth/google/callback → Google's redirect target; resolves the user,
                                stores Sheets refresh_token, sets the JWT
                                cookie, and bounces back to the dashboard.

Distinct from ``app/routers/oauth.py`` which handles the "already-logged-in
operator wants to connect Sheets" case. Sign-in is bootstrap: the user has
no JWT yet, so the callback issues one.

Scopes requested:
    openid email profile         — needed to identify the user.
    spreadsheets.readonly        — needed for the Sheets lead source.
Combining them in one consent means the user authorizes once and gets both
login and Sheets data access. The Sheets refresh_token is stored in the
existing google_oauth_tokens table; the user's google_sub goes onto
``users.google_sub`` for stable identity matching across email changes.

Auto-create policy:
    First time a Google sub doesn't match any existing row, we create a new
    users row with that email + google_sub and a NULL password_hash. They
    can set a password later via the regular /auth/register flow if they want.
"""

from __future__ import annotations

import logging
import secrets
import time
import urllib.parse

import httpx
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.auth import create_access_token
from app.config import settings
from app.db import execute, fetch_one
from app.services.encryption import encrypt

log = logging.getLogger(__name__)

router = APIRouter()


GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://openidconnect.googleapis.com/v1/userinfo"

# Combined login + Sheets scope. ``openid`` makes the userinfo endpoint
# return a stable ``sub`` claim; ``email`` and ``profile`` give us a display
# name. ``spreadsheets.readonly`` lights up the Sheets lead source.
SCOPE = (
    "openid email profile "
    "https://www.googleapis.com/auth/spreadsheets.readonly"
)

# In-memory state store (10min TTL) mirrors the pattern in oauth.py.
_STATE_STORE: dict[str, tuple[str, float]] = {}
_STATE_TTL_SECONDS = 600


def _prune_state() -> None:
    now = time.time()
    expired = [k for k, (_, exp) in _STATE_STORE.items() if exp < now]
    for k in expired:
        _STATE_STORE.pop(k, None)


def _login_redirect_uri() -> str:
    # We deliberately use a DIFFERENT callback URL than the Sheets-only
    # /oauth/google/callback flow so a single Google app can serve both
    # paths cleanly. Operator must register BOTH in the Google Cloud
    # console under "Authorized redirect URIs".
    return (
        getattr(settings, "google_login_redirect_uri", None)
        or settings.google_oauth_redirect_uri.replace(
            "/api/oauth/google/callback",
            "/api/auth/google/callback",
        )
    )


def _ui_redirect(status: str, reason: str = "", token: str | None = None) -> RedirectResponse:
    """Bounce the browser back to the dashboard with status flags.

    JWT is also set as a cookie so the SPA picks it up without a follow-up
    fetch. Frontend can then read ``?google_login=connected`` and call
    /auth/me to confirm.
    """
    params = {"google_login": status}
    if reason:
        params["reason"] = reason
    qs = urllib.parse.urlencode(params)
    response = RedirectResponse(url=f"/?{qs}")
    if token:
        # SameSite=Lax so the cookie survives the cross-origin redirect from
        # Google. Secure means cookie only sent over HTTPS (we're behind nginx
        # with TLS); httponly so JS can't read it.
        response.set_cookie(
            key="omni_jwt",
            value=token,
            max_age=settings.jwt_expire_minutes * 60,
            httponly=True,
            secure=True,
            samesite="lax",
        )
    return response


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.post("/login")
async def login_start() -> dict:
    """Anonymous endpoint — returns the Google authorize URL.

    No auth required because the user IS signing in. The state cookie
    binds the callback to this start request to prevent CSRF.
    """
    if not settings.google_oauth_client_id or not settings.google_oauth_client_secret:
        raise HTTPException(503, "Google sign-in is not configured on this server")

    _prune_state()
    state = secrets.token_urlsafe(32)
    # state value carries no user_id (they don't have one yet), but we still
    # track it so we can reject stale/forged callbacks.
    _STATE_STORE[state] = ("__anon__", time.time() + _STATE_TTL_SECONDS)

    params = {
        "client_id": settings.google_oauth_client_id,
        "redirect_uri": _login_redirect_uri(),
        "response_type": "code",
        "scope": SCOPE,
        "access_type": "offline",
        "prompt": "consent",  # ensure refresh_token even on repeat sign-ins
        "include_granted_scopes": "true",
        "state": state,
    }
    return {"authorize_url": f"{GOOGLE_AUTH_URL}?{urllib.parse.urlencode(params)}"}


@router.get("/callback")
async def login_callback(
    code: str = Query(""),
    state: str = Query(""),
    error: str = Query(""),
) -> RedirectResponse:
    """Google's redirect target. Exchanges code, upserts the user, stores
    Sheets refresh_token, sets the JWT cookie, and bounces to the dashboard.
    """
    if error:
        log.warning("[auth-google] Google returned error=%s", error)
        return _ui_redirect("error", error)

    _prune_state()
    if not _STATE_STORE.pop(state, None):
        return _ui_redirect("error", "invalid_state")
    if not code:
        return _ui_redirect("error", "missing_code")

    # 1. Exchange code → tokens
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            tok_resp = await client.post(
                GOOGLE_TOKEN_URL,
                data={
                    "code": code,
                    "client_id": settings.google_oauth_client_id,
                    "client_secret": settings.google_oauth_client_secret,
                    "redirect_uri": _login_redirect_uri(),
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
        except Exception as e:  # noqa: BLE001
            log.exception("[auth-google] token exchange failed: %s", e)
            return _ui_redirect("error", "token_exchange_failed")
    if tok_resp.status_code >= 400:
        log.error("[auth-google] token HTTP %s: %s", tok_resp.status_code, tok_resp.text[:200])
        return _ui_redirect("error", f"token_http_{tok_resp.status_code}")
    tok = tok_resp.json() or {}
    access_token = tok.get("access_token")
    refresh_token = tok.get("refresh_token")
    granted_scopes = tok.get("scope") or SCOPE
    if not access_token:
        return _ui_redirect("error", "no_access_token")

    # 2. Resolve identity (sub + email)
    async with httpx.AsyncClient(timeout=10) as client:
        try:
            ui = await client.get(
                GOOGLE_USERINFO_URL,
                headers={"Authorization": f"Bearer {access_token}"},
            )
        except Exception as e:  # noqa: BLE001
            log.exception("[auth-google] userinfo failed: %s", e)
            return _ui_redirect("error", "userinfo_failed")
    if ui.status_code >= 400:
        return _ui_redirect("error", f"userinfo_http_{ui.status_code}")
    info = ui.json() or {}
    sub = info.get("sub")
    email = (info.get("email") or "").lower().strip()
    if not sub or not email:
        return _ui_redirect("error", "incomplete_identity")
    if not info.get("email_verified", True):
        return _ui_redirect("error", "email_unverified")

    # 3. Find-or-create user. Match priority: google_sub → email.
    user_id = await _upsert_user(sub=sub, email=email)

    # 4. Store Sheets refresh_token (only present on first consent).
    if refresh_token:
        await execute(
            """
            INSERT INTO google_oauth_tokens
                (user_id, google_email, refresh_token_encrypted, scopes, connected_at)
            VALUES ($1, $2, $3, $4, NOW())
            ON CONFLICT (user_id) DO UPDATE
              SET google_email             = EXCLUDED.google_email,
                  refresh_token_encrypted = EXCLUDED.refresh_token_encrypted,
                  scopes                   = EXCLUDED.scopes,
                  connected_at             = NOW(),
                  last_refresh_at          = NULL
            """,
            user_id,
            email,
            encrypt(refresh_token),
            granted_scopes,
        )
        log.info("[auth-google] stored Sheets refresh_token user=%s email=%s", user_id, email)
    else:
        # No refresh_token can mean two things:
        #   - user revoked + re-consented (Google won't issue another until
        #     they revoke from myaccount.google.com first)
        #   - we already have it from a prior login — that's fine
        log.info(
            "[auth-google] no refresh_token in response (existing grant?) user=%s",
            user_id,
        )

    # Make sure the user has a workspace before we mint a token. First-time
    # Google signups land here with no workspace, so this is the cold path.
    from app.services.workspaces import ensure_default_workspace

    workspace_id = await ensure_default_workspace(user_id, email)
    jwt = create_access_token(user_id, workspace_id)
    return _ui_redirect("connected", token=jwt)


async def _upsert_user(*, sub: str, email: str) -> str:
    """Returns the users.id (as str) for this Google identity.

    Match order:
      1. google_sub — definitive identity.
      2. email — backfills google_sub onto an existing password-registered
         user the first time they sign in with Google.
      3. neither — auto-create.
    """
    row = await fetch_one(
        "SELECT id FROM users WHERE google_sub=$1 LIMIT 1", sub
    )
    if row:
        # Refresh email in case the user changed their Google email
        await execute(
            "UPDATE users SET email=$1 WHERE id=$2 AND email IS DISTINCT FROM $1",
            email, row["id"],
        )
        return str(row["id"])

    row = await fetch_one("SELECT id FROM users WHERE email=$1 LIMIT 1", email)
    if row:
        await execute(
            "UPDATE users SET google_sub=$1 WHERE id=$2 AND google_sub IS NULL",
            sub, row["id"],
        )
        log.info("[auth-google] linked google_sub to existing user email=%s", email)
        return str(row["id"])

    row = await fetch_one(
        """
        INSERT INTO users (email, password_hash, google_sub)
        VALUES ($1, NULL, $2)
        RETURNING id
        """,
        email,
        sub,
    )
    log.info("[auth-google] auto-created user email=%s sub=%s", email, sub)
    return str(row["id"])
