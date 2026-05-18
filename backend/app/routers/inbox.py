"""Unified inbox — aggregates inbound messages/replies across all channels."""

from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import fetch_all, fetch_one

router = APIRouter()


@router.get("")
async def list_inbox(
    channel: str | None = None,
    campaign_id: str | None = None,
    category: str | None = None,
    page: int = 1,
    page_size: int = 30,
    user_id: str = Depends(get_current_user),
):
    """List inbound reply events with lead details, optionally filtered."""
    conditions = [
        "e.event_type IN ('reply_received', 'email_reply', 'linkedin_reply', "
        "'whatsapp_reply', 'sms_reply', 'message_received')"
    ]
    params: list = []
    idx = 1

    if channel:
        conditions.append(f"e.channel=${idx}")
        params.append(channel)
        idx += 1

    if campaign_id:
        conditions.append(f"e.campaign_id=${idx}")
        params.append(campaign_id)
        idx += 1

    if category:
        conditions.append(f"e.meta->>'reply_category'=${idx}")
        params.append(category)
        idx += 1

    where = " AND ".join(conditions)
    offset = (page - 1) * page_size
    rows = await fetch_all(
        f"""SELECT e.*, l.first_name, l.last_name, l.company, l.linkedin_url, l.email AS lead_email
            FROM events e
            LEFT JOIN leads l ON l.id = e.lead_id
            WHERE {where}
            ORDER BY e.occurred_at DESC
            LIMIT ${idx} OFFSET ${idx + 1}""",
        *params,
        page_size,
        offset,
    )
    total = await fetch_one(
        f"SELECT COUNT(*) AS cnt FROM events e WHERE {where}",
        *params,
    )
    return {"messages": rows, "total": total["cnt"], "page": page, "page_size": page_size}


@router.get("/stats")
async def inbox_stats(user_id: str = Depends(get_current_user)):
    """Quick inbox stats: total unread-like count by channel."""
    rows = await fetch_all(
        """SELECT channel, COUNT(*) AS cnt
           FROM events
           WHERE event_type IN (
               'reply_received', 'email_reply', 'linkedin_reply',
               'whatsapp_reply', 'sms_reply', 'message_received'
           )
           GROUP BY channel
           ORDER BY cnt DESC"""
    )
    total = sum(r["cnt"] for r in rows)
    return {"total": total, "by_channel": rows}
