"""Authentication primitives.

Two layers of identity flow through every request:

  * ``user_id``      — who you are (sub claim of the JWT)
  * ``workspace_id`` — which tenant slice your queries are scoped to

JWT shape::

    {"sub": <user_id>, "ws": <workspace_id>, "exp": <epoch>}

``ws`` is optional. When it's missing (legacy tokens issued before the
workspace cutover, or password-only logins that haven't picked a workspace
yet) ``get_current_workspace`` resolves the user's first membership and
falls through with that. Callers that need the workspace explicitly should
depend on ``get_current_workspace``; callers that only need identity can
keep depending on ``get_current_user``.

Tokens are accepted from either:
  * ``Authorization: Bearer <jwt>`` header (CLI / SDK use)
  * ``omni_jwt`` cookie (browser sessions set by the Google sign-in flow)

Header wins when both are present so explicit API calls still work.
"""

from datetime import UTC, datetime, timedelta
from typing import NamedTuple

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings
from app.db import fetch_one, set_request_workspace, system_scope

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
# auto_error=False so we can fall back to the omni_jwt cookie.
bearer = HTTPBearer(auto_error=False)


class AuthContext(NamedTuple):
    """Bundle returned by ``get_current_workspace``.

    Made a NamedTuple (not a dataclass) so downstream routers can unpack
    ``user_id, workspace_id = ...`` when that reads cleaner.
    """

    user_id: str
    workspace_id: str


# ── Passwords ────────────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


# ── JWT mint + decode ────────────────────────────────────────────────────────


def create_access_token(user_id: str, workspace_id: str | None = None) -> str:
    """Mint a JWT. ``workspace_id`` is optional so callers that don't know
    the active workspace yet (e.g. just after Google sign-in) can issue a
    token and let the workspace resolver pick a default."""
    expire = datetime.now(UTC) + timedelta(minutes=settings.jwt_expire_minutes)
    payload: dict[str, object] = {"sub": user_id, "exp": expire}
    if workspace_id:
        payload["ws"] = workspace_id
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> str:
    """Decode and return the ``sub`` (user_id) claim. Raises 401 on any
    failure. Kept str-returning for backwards compatibility with callers
    like notifications/WebSocket that only need identity."""
    return decode_access_token_full(token)["sub"]


def decode_access_token_full(token: str) -> dict:
    """Decode and return the full JWT payload. Used by the workspace
    dependency to read both ``sub`` and ``ws`` in one round trip."""
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError as e:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from e
    if not payload.get("sub"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    return payload


# ── Token extraction ─────────────────────────────────────────────────────────


def _extract_token(request: Request, credentials: HTTPAuthorizationCredentials | None) -> str:
    if credentials and credentials.credentials:
        return credentials.credentials
    cookie_token = request.cookies.get("omni_jwt")
    if cookie_token:
        return cookie_token
    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")


# ── Dependencies ─────────────────────────────────────────────────────────────


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> str:
    """Return the authenticated user_id. Reads JWT from header or cookie."""
    token = _extract_token(request, credentials)
    return decode_access_token(token)


async def get_current_workspace(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer),
) -> AuthContext:
    """Return ``(user_id, workspace_id)`` for the current request.

    Resolution order for the workspace:
      1. ``ws`` claim on the JWT (set when the user picks a workspace).
      2. The user's first membership row, ordered by joined_at ASC.
         This is the legacy-token + first-login path; the frontend should
         immediately call ``/workspaces/switch`` if it wants to pick a
         different one.

    Raises 403 if the user has zero workspace memberships, which shouldn't
    happen post-migration but we surface it explicitly rather than 500ing.
    """
    token = _extract_token(request, credentials)
    payload = decode_access_token_full(token)
    user_id = payload["sub"]
    workspace_id = payload.get("ws")

    # workspace_members is not workspace-scoped (it IS the tenancy table),
    # so we have to read it under system_scope() to bypass RLS. Resolve the
    # workspace_id inside the system scope; bind it to the request context
    # AFTER the scope exits so the system-scope reset doesn't clobber it.
    resolved: str | None = None
    async with system_scope():
        if workspace_id:
            row = await fetch_one(
                "SELECT 1 FROM workspace_members WHERE user_id=$1 AND workspace_id=$2",
                user_id,
                workspace_id,
            )
            if row:
                resolved = str(workspace_id)

        if resolved is None:
            row = await fetch_one(
                """
                SELECT workspace_id FROM workspace_members
                WHERE user_id=$1
                ORDER BY joined_at ASC
                LIMIT 1
                """,
                user_id,
            )
            if row:
                resolved = str(row["workspace_id"])

    if resolved is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User has no workspace membership",
        )

    set_request_workspace(resolved)
    return AuthContext(user_id=user_id, workspace_id=resolved)
