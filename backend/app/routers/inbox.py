"""Unified inbox — projection of inbound/outbound messages.

Reads ``messages`` (maintained by the projector from ``message.received``
and ``message.sent`` events). Groups by contact for the thread list view.
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
    channel: str
    direction: str
    subject: str | None
    body: str | None
    classification: str | None
    confidence: float | None
    metadata: dict[str, Any]
    occurred_at: datetime


class InboxThread(BaseModel):
    contact_id: uuid.UUID
    last_message_at: datetime
    message_count: int
    last_classification: str | None
    last_snippet: str | None
    last_channel: str | None


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
          contact_id,
          MAX(occurred_at)                              AS last_message_at,
          COUNT(*)                                      AS message_count,
          (ARRAY_AGG(classification ORDER BY occurred_at DESC))[1] AS last_classification,
          (ARRAY_AGG(LEFT(body, 200)  ORDER BY occurred_at DESC))[1] AS last_snippet,
          (ARRAY_AGG(channel          ORDER BY occurred_at DESC))[1] AS last_channel
        FROM messages
        WHERE contact_id IS NOT NULL
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
        SELECT id, contact_id, channel, direction, subject, body,
               classification, confidence, metadata, occurred_at
        FROM messages
        WHERE contact_id = $1
        ORDER BY occurred_at ASC
        LIMIT $2
        """,
        contact_id,
        limit,
    )
    return [InboxMessage.model_validate(r) for r in rows]
