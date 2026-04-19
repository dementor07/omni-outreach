import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

router = APIRouter()
log = logging.getLogger(__name__)

# ── In-memory SSE subscribers (per user_id) ─────────────────────────────────
_subscribers: dict[str, list[asyncio.Queue]] = {}


async def push_notification(user_id: str, notif: dict) -> None:
    """Insert a notification row and push to any active SSE subscribers."""
    row = await fetch_one(
        """INSERT INTO notifications (user_id, type, title, body, link, meta)
           VALUES ($1, $2, $3, $4, $5, $6)
           RETURNING id, type, title, body, link, is_read, meta, created_at""",
        user_id, notif["type"], notif["title"],
        notif.get("body"), notif.get("link"), json.dumps(notif.get("meta", {})),
    )
    if row and user_id in _subscribers:
        payload = {**row, "created_at": row["created_at"].isoformat() if row.get("created_at") else None,
                   "id": str(row["id"])}
        for q in _subscribers[user_id]:
            await q.put(payload)


# ── SSE stream ──────────────────────────────────────────────────────────────

@router.get("/stream")
async def notification_stream(user_id: str = Depends(get_current_user)):
    q: asyncio.Queue = asyncio.Queue()
    _subscribers.setdefault(user_id, []).append(q)

    async def event_generator():
        try:
            yield f"data: {json.dumps({'type': 'connected'})}\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=30.0)
                    yield f"data: {json.dumps(msg, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            _subscribers.get(user_id, []).remove(q) if q in _subscribers.get(user_id, []) else None

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ── REST endpoints ──────────────────────────────────────────────────────────

@router.get("")
async def list_notifications(
    unread_only: bool = False,
    limit: int = Query(default=30, le=100),
    user: dict = Depends(get_current_user),
):
    user_id = str(user["id"])
    if unread_only:
        rows = await fetch_all(
            "SELECT * FROM notifications WHERE user_id=$1 AND is_read=FALSE ORDER BY created_at DESC LIMIT $2",
            user_id, limit,
        )
    else:
        rows = await fetch_all(
            "SELECT * FROM notifications WHERE user_id=$1 ORDER BY created_at DESC LIMIT $2",
            user_id, limit,
        )
    count = await fetch_one(
        "SELECT COUNT(*) as cnt FROM notifications WHERE user_id=$1 AND is_read=FALSE", user_id,
    )
    return {"notifications": rows, "unread_count": count["cnt"] if count else 0}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: str, user: dict = Depends(get_current_user)):
    await execute(
        "UPDATE notifications SET is_read=TRUE WHERE id=$1 AND user_id=$2",
        notification_id, str(user["id"]),
    )
    return {"status": "ok"}


@router.post("/read-all")
async def mark_all_read(user: dict = Depends(get_current_user)):
    await execute(
        "UPDATE notifications SET is_read=TRUE WHERE user_id=$1 AND is_read=FALSE",
        str(user["id"]),
    )
    return {"status": "ok"}
