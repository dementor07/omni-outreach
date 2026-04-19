"""Email open and click tracking via transparent pixel and redirect links.

Endpoints are PUBLIC (no auth) — they're embedded in sent emails.
"""
import uuid
from urllib.parse import unquote

from fastapi import APIRouter, Request, Response
from fastapi.responses import RedirectResponse

from app.db import execute, fetch_one

router = APIRouter()

# 1x1 transparent GIF
PIXEL = bytes.fromhex(
    "47494638396101000100800100ffffff"
    "00000021f90401000001002c00000000"
    "0100010000020244013b"
)


async def _record_event(event_id: str, event_type: str, request: Request):
    """Record an open or click event for a tracked email."""
    row = await fetch_one(
        "SELECT lead_id, campaign_id, meta FROM events WHERE id=$1",
        event_id,
    )
    if not row:
        return
    ua = request.headers.get("user-agent", "")
    ip = request.client.host if request.client else "unknown"
    await execute(
        """INSERT INTO events (lead_id, campaign_id, channel, event_type, meta)
           VALUES ($1, $2, 'email', $3, $4::jsonb)
           ON CONFLICT DO NOTHING""",
        row["lead_id"],
        row["campaign_id"],
        event_type,
        f'{{"ip":"{ip}","ua":"{ua}","parent_event":"{event_id}"}}',
    )


@router.get("/pixel/{event_id}.gif")
async def track_open(event_id: str, request: Request):
    """Transparent tracking pixel embedded in emails."""
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
async def track_click(event_id: str, url: str, request: Request):
    """Redirect link with click tracking. url param is the actual destination."""
    await _record_event(event_id, "email_clicked", request)
    destination = unquote(url)
    # Basic URL validation to prevent open redirect
    if not destination.startswith(("http://", "https://")):
        destination = "https://" + destination
    return RedirectResponse(url=destination, status_code=302)


def inject_tracking(html: str, event_id: str, base_url: str) -> str:
    """Inject tracking pixel and wrap links in click-tracking redirects.
    
    Args:
        html: The email HTML body.
        event_id: The event ID for the sent email event.
        base_url: The public base URL of the API (e.g. https://api.omni.com).
    
    Returns:
        Modified HTML with tracking pixel and wrapped links.
    """
    import re
    from urllib.parse import quote

    # Wrap href links in click tracking
    def replace_link(match: re.Match) -> str:
        original_url = match.group(1)
        # Don't wrap unsubscribe or tracking links
        if "unsubscribe" in original_url.lower() or "/track/" in original_url:
            return match.group(0)
        tracked = f"{base_url}/track/click/{event_id}?url={quote(original_url)}"
        return f'href="{tracked}"'

    tracked_html = re.sub(r'href="([^"]+)"', replace_link, html)

    # Append tracking pixel before closing </body>
    pixel_tag = f'<img src="{base_url}/track/pixel/{event_id}.gif" width="1" height="1" style="display:none" alt="" />'
    if "</body>" in tracked_html:
        tracked_html = tracked_html.replace("</body>", f"{pixel_tag}</body>")
    else:
        tracked_html += pixel_tag

    return tracked_html
