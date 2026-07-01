"""Signed callback tokens for channel.n8n wait-for-callback (N8N-001 Part 3).

When a ``channel.n8n`` node is configured ``wait_for_callback=True`` it parks the
lead and hands n8n a token encoding ``{workspace_id, lead_id, node_id}`` plus an
expiry. n8n POSTs that token back to ``/n8n/callback/{token}`` to resume exactly
that parked lead. The token is HMAC-signed with the app secret so it cannot be
forged; an expired or tampered token fails validation and the callback 404s.

Same compact ``<payload_b64>.<sig_b64>`` shape as email_tracking.make_token, with
an added ``exp`` (unix seconds) enforced on parse.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64url_decode(s: str) -> bytes:
    pad = "=" * (-len(s) % 4)
    return base64.urlsafe_b64decode(s + pad)


def make_callback_token(
    secret: str,
    *,
    workspace_id: str,
    lead_id: str,
    node_id: str,
    ttl_seconds: int,
) -> str:
    """Sign a callback token that expires ``ttl_seconds`` from now."""
    payload = json.dumps(
        {
            "w": workspace_id,
            "l": lead_id,
            "n": node_id,
            "exp": int(time.time()) + int(ttl_seconds),
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    sig = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
    return f"{_b64url(payload)}.{_b64url(sig)}"


def parse_callback_token(secret: str, token: str, *, now: float | None = None) -> dict[str, Any] | None:
    """Verify signature + expiry. Returns ``{workspace_id, lead_id, node_id}`` or
    None when the signature is invalid, the token is malformed, or it has expired."""
    try:
        payload_b64, sig_b64 = token.split(".", 1)
        payload = _b64url_decode(payload_b64)
        expected = hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected, _b64url_decode(sig_b64)):
            return None
        data = json.loads(payload)
    except Exception:  # noqa: BLE001
        return None
    exp = data.get("exp")
    if not isinstance(exp, (int, float)):
        return None
    if (now if now is not None else time.time()) > exp:
        return None
    return {"workspace_id": data.get("w"), "lead_id": data.get("l"), "node_id": data.get("n")}
