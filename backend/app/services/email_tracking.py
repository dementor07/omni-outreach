"""T3 — email open/click tracking.

Two pure pieces (no I/O, unit-testable) + one DB read on the public endpoints:

  * ``make_token`` / ``parse_token`` — an HMAC-signed, URL-safe token encoding
    ``{workspace_id, lead_id, contact_id}`` so the public pixel/redirect
    endpoints can attribute a hit to a lead WITHOUT exposing raw ids or trusting
    the caller. A tampered token fails the constant-time signature check.

  * ``inject_tracking`` — given a rendered HTML email body, appends a 1×1 open
    pixel and rewrites ``<a href>`` links to the click-redirect endpoint. Pure
    string transform so render.py stays I/O-free.

The endpoints (routers/tracking.py) log an ``email.opened`` / ``email.clicked``
event; the projector materialises ``omni_email_tracking`` (migration 034).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
from typing import Any

# 1x1 transparent GIF — the open pixel body.
PIXEL_GIF = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7"
)

_HREF_RE = re.compile(r'href=(["\'])(https?://[^"\']+)\1', re.IGNORECASE)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_token(secret: str, *, workspace_id: str, lead_id: str | None, contact_id: str | None) -> str:
    """Sign a compact attribution token. Format: <payload_b64>.<sig_b64>."""
    payload = json.dumps(
        {"w": workspace_id, "l": lead_id, "c": contact_id},
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64url(payload)}.{_b64url(sig)}"


def parse_token(secret: str, token: str) -> dict[str, Any] | None:
    """Verify + decode a token. Returns {workspace_id, lead_id, contact_id} or
    None when the signature is invalid / the token is malformed."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _b64url_decode(payload_b64)
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return None
        data = json.loads(payload)
    except Exception:  # noqa: BLE001
        return None
    return {"workspace_id": data.get("w"), "lead_id": data.get("l"), "contact_id": data.get("c")}


def inject_tracking(html: str, *, base: str, token: str) -> str:
    """Rewrite links to the click-redirect + append the open pixel.

    ``base`` is the external base URL (no trailing slash). Idempotent-ish: links
    already pointing at the tracker are left alone."""
    base = base.rstrip("/")
    click_prefix = f"{base}/track/click/{token}"

    def _rewrite(m: re.Match[str]) -> str:
        quote, url = m.group(1), m.group(2)
        if url.startswith(f"{base}/track/"):
            return m.group(0)
        wrapped = f"{click_prefix}?u={_b64url(url.encode('utf-8'))}"
        return f"href={quote}{wrapped}{quote}"

    rewritten = _HREF_RE.sub(_rewrite, html or "")
    pixel = f'<img src="{base}/track/open/{token}.gif" width="1" height="1" alt="" style="display:none" />'
    return f"{rewritten}{pixel}"


def decode_click_url(u: str) -> str | None:
    """Decode the ``u`` query param back to the original destination URL."""
    try:
        url = _b64url_decode(u).decode("utf-8")
    except Exception:  # noqa: BLE001
        return None
    # Only http(s) destinations — never an open redirect to javascript:/data:.
    return url if url.startswith(("http://", "https://")) else None
