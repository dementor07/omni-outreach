"""Email open and click tracking via transparent pixel and redirect links.

Endpoints are PUBLIC (no auth) — they're embedded in sent emails.
URLs are HMAC-signed so forged event IDs are rejected.
"""

import hashlib
import hmac
import json
import logging
from urllib.parse import quote, unquote, urlparse

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import RedirectResponse

from app.config import settings
from app.db import execute, fetch_one, set_request_workspace, system_scope

router = APIRouter()
log = logging.getLogger(__name__)

# 1x1 transparent GIF
PIXEL = bytes.fromhex("47494638396101000100800100ffffff00000021f90401000001002c000000000100010000020244013b")


def _sign(event_id: str) -> str:
    """Generate HMAC-SHA256 signature for an event_id."""
    return hmac.new(settings.secret_key.encode(), event_id.encode(), hashlib.sha256).hexdigest()[:16]


def _verify_sig(event_id: str, sig: str) -> bool:
    """Constant-time verification of HMAC signature."""
    expected = _sign(event_id)
    return hmac.compare_digest(sig, expected)


async def _record_event(event_id: str, event_type: str, request: Request):
    """Record an open or click event for a tracked email.

    Public endpoint (signed-only, no JWT) — we resolve the event's workspace
    via system_scope, then bind it so subsequent writes land in the right
    tenant under RLS.
    """
    async with system_scope():
        row = await fetch_one(
            "SELECT lead_id, campaign_id, meta, workspace_id FROM events WHERE id=$1",
            event_id,
        )
    if not row:
        return
    set_request_workspace(str(row["workspace_id"]))
    ua = request.headers.get("user-agent", "")[:512]
    ip = request.client.host if request.client else "unknown"
    meta = json.dumps({"ip": ip, "ua": ua, "parent_event": event_id})
    await execute(
        """INSERT INTO events (lead_id, campaign_id, channel, event_type, meta)
           VALUES ($1, $2, 'email', $3, $4::jsonb)
           ON CONFLICT DO NOTHING""",
        row["lead_id"],
        row["campaign_id"],
        event_type,
        meta,
    )

    # Plumb the engagement timestamps onto the lead row so condition_*/event_*
    # nodes that read lead.email_opened_at / link_clicked_at can branch
    # correctly. Without this update the events table has the data but the
    # sequencer never sees it.
    if event_type == "email_opened":
        await execute(
            "UPDATE leads SET email_opened_at = COALESCE(email_opened_at, NOW()) WHERE id=$1",
            row["lead_id"],
        )
    elif event_type == "email_clicked":
        await execute(
            "UPDATE leads SET link_clicked_at = COALESCE(link_clicked_at, NOW()) WHERE id=$1",
            row["lead_id"],
        )

    # Nudge the sequencer in case the lead is parked at an event_* node.
    try:
        from app.services import sequencer
        await sequencer.evaluate_conditions(str(row["lead_id"]))
    except Exception as e:  # noqa: BLE001 — engagement plumbing must never break the pixel response
        log.warning(f"[tracking] evaluate_conditions failed for lead {row['lead_id']}: {e}")


@router.get("/pixel/{event_id}.gif")
async def track_open(event_id: str, sig: str = "", request: Request = None):
    """Transparent tracking pixel embedded in emails. Requires valid HMAC sig."""
    if not sig or not _verify_sig(event_id, sig):
        return Response(content=PIXEL, media_type="image/gif")  # silent fail — no event recorded
    await _record_event(event_id, "email_opened", request)
    return Response(
        content=PIXEL,
        media_type="image/gif",
        headers={
            "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
            "Pragma": "no-cache",
        },
    )


@router.get("/click/{event_id}")
async def track_click(event_id: str, url: str, sig: str = "", request: Request = None):
    """Redirect link with click tracking. Requires valid HMAC sig."""
    destination = unquote(url)
    parsed = urlparse(destination)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise HTTPException(status_code=400, detail="Invalid redirect URL")
    if sig and _verify_sig(event_id, sig):
        await _record_event(event_id, "email_clicked", request)
    return RedirectResponse(url=destination, status_code=302)


def inject_tracking(html: str, event_id: str, base_url: str) -> str:
    """Inject tracking pixel and wrap links in click-tracking redirects.

    URLs include HMAC signature for tamper protection.

    Args:
        html: The email HTML body.
        event_id: The event ID for the sent email event.
        base_url: The public base URL of the API (e.g. https://api.omni.com).

    Returns:
        Modified HTML with tracking pixel and wrapped links.
    """
    import re

    sig = _sign(event_id)

    # Wrap href links in click tracking
    def replace_link(match: re.Match) -> str:
        original_url = match.group(1)
        # Don't wrap unsubscribe or tracking links
        if "unsubscribe" in original_url.lower() or "/track/" in original_url:
            return match.group(0)
        tracked = f"{base_url}/track/click/{event_id}?url={quote(original_url)}&sig={sig}"
        return f'href="{tracked}"'

    tracked_html = re.sub(r'href="([^"]+)"', replace_link, html)

    # Append tracking pixel before closing </body>
    pixel_tag = f'<img src="{base_url}/track/pixel/{event_id}.gif?sig={sig}" width="1" height="1" style="display:none" alt="" />'
    if "</body>" in tracked_html:
        tracked_html = tracked_html.replace("</body>", f"{pixel_tag}</body>")
    else:
        tracked_html += pixel_tag

    return tracked_html
