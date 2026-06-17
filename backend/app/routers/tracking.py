"""T3 — public email open/click tracking endpoints.

  GET /track/open/{token}.gif      → log an open, return a 1x1 transparent GIF
  GET /track/click/{token}?u=<b64> → log a click, 302 to the decoded URL

UNAUTHENTICATED by design — a recipient's mail client / browser fetches these
with no session. Trust comes from the HMAC-signed token (services.email_tracking)
which encodes the workspace/lead/contact; a tampered token simply fails to
attribute (we still serve the pixel / redirect so the recipient never sees a
broken image or dead link). Both emit an event the projector materialises into
omni_email_tracking; the workspace is taken from the token, never the request.
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Response
from fastapi.responses import RedirectResponse

from app.config import settings
from app.db import system_scope
from app.services import bus, email_tracking

router = APIRouter()

_GIF_HEADERS = {"Cache-Control": "no-store, no-cache, must-revalidate, private", "Pragma": "no-cache"}


async def _log_hit(token: str, event_type: str, url: str | None) -> None:
    """Attribute a hit from a verified token. Silent no-op on a bad token so the
    public response is never blocked by attribution failure."""
    claims = email_tracking.parse_token(settings.secret_key, token)
    if not claims or not claims.get("workspace_id"):
        return
    try:
        async with system_scope():
            await bus.publish_event(
                workspace_id=claims["workspace_id"],
                event_type=f"email.{event_type}",  # email.opened | email.clicked
                entity_type="email_tracking",
                entity_id=claims.get("lead_id"),
                payload={
                    "lead_id": claims.get("lead_id"),
                    "contact_id": claims.get("contact_id"),
                    "kind": event_type,
                    "url": url,
                },
            )
    except Exception:  # noqa: BLE001 — never let logging break the pixel/redirect
        pass


@router.get("/open/{token}.gif", summary="Email open pixel (logs an open)")
async def track_open(token: str) -> Response:
    await _log_hit(token, "open", None)
    return Response(content=email_tracking.PIXEL_GIF, media_type="image/gif", headers=_GIF_HEADERS)


@router.get("/click/{token}", summary="Email click redirect (logs a click, 302s on)")
async def track_click(token: str, u: str = Query(..., description="base64url of the destination URL")) -> Response:
    target = email_tracking.decode_click_url(u)
    await _log_hit(token, "click", target)
    # Fall back to the public base when the URL is missing/invalid rather than
    # erroring — the recipient should always land somewhere safe.
    destination = target or settings.get_public_base_url()
    return RedirectResponse(url=destination, status_code=302)
