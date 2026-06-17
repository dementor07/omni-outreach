"""Unified inbox — projection of inbound/outbound messages.

Reads ``omni_messages`` (maintained by the projector from ``message.received``
and ``message.sent`` events). Groups by contact for the thread list view.

B3 adds the reply seam:
  POST /inbox/threads/{contact_id}/suggest  → AI-suggested draft (fail-open)
  POST /inbox/threads/{contact_id}/reply    → DNC-checked send via the muscle

A manual reply rides the SAME spine as a canvas channel node: it re-checks the
contact-level suppression gate (T1), then builds an ActionCommand and publishes
it to the muscle, which delivers and emits ``message.sent`` — so the outbound
shows up in this very projection. No bespoke send path.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.core.events import ChannelType
from app.db import fetch_all, fetch_one, system_scope
from app.execution import commands
from app.services import reply_drafter, suppression

router = APIRouter()

# Inbox channel string → muscle ChannelType. Mirrors commands.NODE_CHANNEL but
# keyed by the bare channel name the projection stores (no "channel." prefix).
_CHANNEL_BY_NAME: dict[str, ChannelType] = {
    "email": ChannelType.EMAIL,
    "sms": ChannelType.SMS,
    "voice": ChannelType.VOICE,
    "linkedin": ChannelType.LINKEDIN_DM,
    "linkedin_dm": ChannelType.LINKEDIN_DM,
    "whatsapp": ChannelType.WHATSAPP,
    "instagram": ChannelType.INSTAGRAM,
    "telegram": ChannelType.TELEGRAM,
}

# Channel → the connection provider that holds its sending credential. Used to
# resolve the workspace connection for a manual reply (the canvas path gets the
# connection name from the node manifest; a manual reply has no node).
_PROVIDER_BY_CHANNEL: dict[ChannelType, str] = {
    ChannelType.EMAIL: "smtp",
    ChannelType.SMS: "twilio",
    ChannelType.VOICE: "retell",
    ChannelType.LINKEDIN_DM: "unipile",
    ChannelType.WHATSAPP: "unipile",
    ChannelType.INSTAGRAM: "unipile",
    ChannelType.TELEGRAM: "unipile",
}


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
        FROM omni_messages
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
        FROM omni_messages
        WHERE contact_id = $1
        ORDER BY occurred_at ASC
        LIMIT $2
        """,
        contact_id,
        limit,
    )
    return [InboxMessage.model_validate(r) for r in rows]


# ── B3: AI-suggested reply draft ─────────────────────────────────────────────


class SuggestOut(BaseModel):
    draft: str
    source: str = Field(description="llm | template — provenance of the draft")


@router.post(
    "/threads/{contact_id}/suggest",
    response_model=SuggestOut,
    summary="AI-suggest a reply draft for a thread (fail-open to a template)",
)
async def suggest_reply(
    contact_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current_workspace),
) -> SuggestOut:
    rows = await fetch_all(
        """
        SELECT direction, body, classification
        FROM omni_messages
        WHERE contact_id = $1
        ORDER BY occurred_at ASC
        LIMIT 20
        """,
        contact_id,
    )
    messages = [dict(r) for r in rows]
    # the intent of the LATEST inbound message shapes the fallback template.
    last_inbound_intent = next(
        (m["classification"] for m in reversed(messages) if m["direction"] == "inbound"),
        None,
    )
    draft, source = await reply_drafter.suggest_reply(
        str(ctx.workspace_id), messages, last_inbound_intent
    )
    return SuggestOut(draft=draft, source=source)


# ── B3: send a reply through the muscle (DNC re-checked) ──────────────────────


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=10000)
    subject: str | None = Field(None, max_length=500)
    channel: str | None = Field(
        None, description="Override channel; defaults to the thread's last channel"
    )


class ReplyAccepted(BaseModel):
    status: str = "queued"
    channel: str
    correlation_id: uuid.UUID


@router.post(
    "/threads/{contact_id}/reply",
    response_model=ReplyAccepted,
    summary="Send a manual reply on a thread (DNC-checked, dispatched to the muscle)",
)
async def send_reply(
    contact_id: uuid.UUID,
    payload: ReplyIn,
    ctx: AuthContext = Depends(get_current_workspace),
) -> ReplyAccepted:
    workspace_id = str(ctx.workspace_id)

    contact = await fetch_one(
        """
        SELECT id, email, first_name, last_name, company, headline,
               linkedin_url, phone, source, custom_fields
        FROM omni_contacts WHERE id = $1
        """,
        contact_id,
    )
    if not contact:
        raise HTTPException(status_code=404, detail="contact not found")
    contact = dict(contact)

    # Pick the channel: explicit override, else the thread's last channel.
    channel_name = payload.channel
    if not channel_name:
        last = await fetch_one(
            "SELECT channel FROM omni_messages WHERE contact_id = $1 "
            "ORDER BY occurred_at DESC LIMIT 1",
            contact_id,
        )
        channel_name = (last or {}).get("channel") if last else None
    channel = _CHANNEL_BY_NAME.get((channel_name or "").lower())
    if channel is None:
        raise HTTPException(
            status_code=400,
            detail=f"unsupported or unknown reply channel: {channel_name!r}",
        )

    # T1: a manual reply is still an outbound send — the DNC gate applies. A
    # suppressed contact cannot be messaged on ANY channel, inbox included.
    async with system_scope():
        blocked, reason = await suppression.is_suppressed(workspace_id, contact)
    if blocked:
        raise HTTPException(
            status_code=409,
            detail=f"contact is suppressed ({reason}) — reply blocked by DNC policy",
        )

    # Resolve the workspace connection for this channel's provider (most recent).
    provider = _PROVIDER_BY_CHANNEL.get(channel)
    connection_name: str | None = None
    if provider:
        async with system_scope():
            conn = await fetch_one(
                "SELECT name FROM omni_connections WHERE workspace_id = $1 "
                "AND provider = $2 ORDER BY connected_at DESC LIMIT 1",
                workspace_id,
                provider,
            )
        if conn:
            connection_name = conn["name"]

    # Synthesize a one-shot lead context for this contact (no live workflow lead
    # for a manual reply). build_command renders the channel payload + mints the
    # credential ref the same way a canvas channel node does.
    correlation_id = str(uuid.uuid4())
    synthetic_lead: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "workflow_id": None,
        "contact_id": str(contact_id),
        "custom_fields": {},
    }
    body_payload: dict[str, Any] = {"body": payload.body}
    if payload.subject:
        body_payload["subject"] = payload.subject

    command = await commands.build_command(
        workspace_id=workspace_id,
        channel=channel,
        lead=synthetic_lead,
        contact=contact,
        node_id="inbox-reply",
        payload=body_payload,
        connection_name=connection_name,
        correlation_id=correlation_id,
    )
    await commands.publish_command(command)

    return ReplyAccepted(
        status="queued", channel=channel.value, correlation_id=uuid.UUID(correlation_id)
    )
