import hmac
import os
import time
from typing import Any

from dotenv import load_dotenv
from fastapi import HTTPException, Request, Response, status
from itsdangerous import BadSignature, URLSafeSerializer

load_dotenv()

COOKIE_NAME = "dashboard_session"
ROLE_ADMIN = "admin"


def _session_secret() -> str:
    secret = os.getenv("DASHBOARD_SESSION_SECRET", "").strip()
    if not secret:
        secret = os.getenv("DASHBOARD_ADMIN_TOKEN", "").strip()
    if not secret:
        raise RuntimeError("Missing DASHBOARD_SESSION_SECRET or DASHBOARD_ADMIN_TOKEN")
    return secret


def _serializer() -> URLSafeSerializer:
    return URLSafeSerializer(_session_secret(), salt="outreach-dashboard-session")


def validate_admin_token(token: str) -> bool:
    configured = os.getenv("DASHBOARD_ADMIN_TOKEN", "").strip()
    provided = (token or "").strip()
    if not configured or not provided:
        return False
    return hmac.compare_digest(configured, provided)


def issue_session(response: Response, actor: str = ROLE_ADMIN) -> None:
    now = int(time.time())
    payload = {"role": ROLE_ADMIN, "actor": actor, "iat": now}
    signed = _serializer().dumps(payload)
    max_age = int(os.getenv("DASHBOARD_SESSION_MAX_AGE_SECONDS", "43200"))
    secure = os.getenv("DASHBOARD_COOKIE_SECURE", "false").lower() == "true"
    response.set_cookie(
        key=COOKIE_NAME,
        value=signed,
        max_age=max_age,
        httponly=True,
        secure=secure,
        samesite="lax",
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME)


def get_session(request: Request) -> dict[str, Any] | None:
    raw = request.cookies.get(COOKIE_NAME)
    if not raw:
        return None
    try:
        payload = _serializer().loads(raw)
    except BadSignature:
        return None

    if payload.get("role") != ROLE_ADMIN:
        return None

    issued = int(payload.get("iat", 0))
    max_age = int(os.getenv("DASHBOARD_SESSION_MAX_AGE_SECONDS", "43200"))
    if issued <= 0 or int(time.time()) - issued > max_age:
        return None
    return payload


def require_admin(request: Request) -> dict[str, Any]:
    session = get_session(request)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return session

