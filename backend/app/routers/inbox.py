"""Unified inbox — projection of inbound message events.

Every inbound reply (email, LinkedIn, WhatsApp, SMS, …) is a
``message.received`` event in the log. This router groups them by
``contact_id`` so the UI can render a chat-style view.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth import AuthContext, get_current_workspace
from app.db import fetch_all

router = APIRouter()


class InboxMessage(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID | None
    channel: str | None
    direction: str
    body: str | None
    subject: str | None
    classification: str | None
    confidence: float | None
    occurred_at: datetime
    payload: dict[str, Any]


class InboxThread(BaseModel):
    contact_id: uuid.UUID
    last_message_at: datetime
    unread_count: int
    last_classification: str | None
    last_snippet: str | None


@router.get(
    "/threads",
    response_model=list[InboxThread],
    summary="List inbox threads (one per contact, latest-first)",
)
async def list_threads(
    _: AuthContext = Depends(get_current_workspace),
    limit: int = Query(50, ge=1, le=200),
) -> list[InboxThread]:
    rows = await fetch_all(
        """
        SELECT
          (payload->>'contact_id')::uuid           AS contact_id,
          MAX(occurred_at)                         AS last_message_at,
          COUNT(*) FILTER (WHERE (payload->>'read')::boolean IS NOT TRUE) AS unread_count,
          (ARRAY_AGG(payload->>'classification' ORDER BY occurred_at DESC))[1] AS last_classification,
          (ARRAY_AGG(LEFT(payload->>'body', 200) ORDER BY occurred_at DESC))[1] AS last_snippet
        FROM events
        WHERE event_type = 'message.received'
          AND payload ? 'contact_id'
        GROUP BY contact_id
        ORDER BY last_message_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [InboxThread.model_validate(r) for r in rows]


@router.get(
    "/threads/{contact_id}",
    response_model=list[InboxMessage],
    summary="Fetch the full message history for one contact",
)
async def get_thread(
    contact_id: uuid.UUID,
    _: AuthContext = Depends(get_current_workspace),
    limit: int = Query(200, ge=1, le=1000),
) -> list[InboxMessage]:
    rows = await fetch_all(
        """
        SELECT
          id,
          (payload->>'contact_id')::uuid       AS contact_id,
          (payload->>'channel')                AS channel,
          COALESCE(payload->>'direction', 'inbound') AS direction,
          (payload->>'body')                   AS body,
          (payload->>'subject')                AS subject,
          (payload->>'classification')         AS classification,
          (payload->>'confidence')::float      AS confidence,
          occurred_at,
          payload
        FROM events
        WHERE event_type IN ('message.received', 'message.sent')
          AND (payload->>'contact_id')::uuid = $1
        ORDER BY occurred_at ASC
        LIMIT $2
        """,
        contact_id,
        limit,
    )
    return [InboxMessage.model_validate(r) for r in rows]
