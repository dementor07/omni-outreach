"""Unified inbox — projection of inbound/outbound messages.

Reads ``omni_messages`` (maintained by the projector from ``message.received``
and ``message.sent`` events). Groups by contact for the thread list view.

B3 adds the reply seam:
  POST /inbox/threads/{contact_id}/suggest  → AI-suggested draft (fail-open)
  POST /inbox/threads/{contact_id}/reply    → DNC-checked send via the muscle

A manual reply rides the SAME command/result spine as a canvas channel node: it
re-checks the contact-level suppression gate (T1), then builds an ActionCommand
and publishes it to the muscle. A durable send-outcome row records the result;
the inbox itself reads the provider's bidirectional thread as source of truth.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.core.events import ChannelType
from app.db import execute as db_execute
from app.db import fetch_all, fetch_one, system_scope
from app.execution import commands
from app.services import reply_drafter, suppression
from app.services.unipile_client import UnipileClient

router = APIRouter()
log = logging.getLogger("inbox")

# Deterministic namespace so a Unipile chat message maps to a stable InboxMessage id
# (a React key, and idempotent across re-opens of the same thread).
_UNIPILE_MSG_NS = uuid.UUID("b3f5c1a0-6d2e-4a7b-9c8d-2e1f0a3b4c5d")


def _parse_ts(value: Any) -> datetime:
    """Unipile timestamps are ISO-8601 with a trailing Z. Fall back to now (UTC)."""
    if not value:
        return datetime.now(UTC)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return datetime.now(UTC)

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

_ACCOUNT_KIND_BY_CHANNEL: dict[ChannelType, str] = {
    ChannelType.EMAIL: "email",
    ChannelType.SMS: "sms",
    ChannelType.VOICE: "voice",
    ChannelType.WHATSAPP: "whatsapp",
    ChannelType.INSTAGRAM: "instagram",
    ChannelType.TELEGRAM: "telegram",
    ChannelType.LINKEDIN_DM: "linkedin",
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
    first_name: str | None
    last_name: str | None
    company: str | None
    headline: str | None
    last_message_at: datetime
    message_count: int
    inbound_count: int
    sent_count: int
    last_inbound_at: datetime | None
    last_classification: str | None
    last_snippet: str | None
    last_channel: str | None


class InboxNotification(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID
    first_name: str | None
    last_name: str | None
    company: str | None
    channel: str
    snippet: str | None
    classification: str | None
    occurred_at: datetime


@router.get(
    "/threads",
    response_model=list[InboxThread],
    summary="List inbox threads — every contact we've engaged (sent OR received), latest-first",
)
async def list_threads(
    _: AuthContext = Depends(get_current_workspace),
    limit: int = Query(50, ge=1, le=200),
    workflow_id: uuid.UUID | None = Query(
        None, description="Campaign filter — only threads for contacts enrolled in this workflow"
    ),
) -> list[InboxThread]:
    # A "thread" is a contact we have ENGAGED — an inbound reply (omni_messages) OR
    # an outbound send (omni_send_outcomes). The inbox is the whole conversation, not
    # just the contacts who happened to reply. Names come from omni_contacts (the list
    # used to render the contact_id itself). RLS scopes every table to the workspace.
    rows = await fetch_all(
        """
        WITH engaged AS (
            SELECT contact_id, occurred_at, channel,
                   'inbound'::text AS direction,
                   LEFT(body, 200) AS snippet, classification
            FROM omni_messages
            WHERE contact_id IS NOT NULL
            UNION ALL
            -- A contact gets ONE connection request; extra 'sent' rows are the
            -- re-fire artifact. The thread detail already collapses them, so the
            -- list has to as well or the two disagree about how many messages a
            -- conversation holds.
            SELECT contact_id, occurred_at, channel,
                   'outbound'::text AS direction,
                   NULL AS snippet, NULL AS classification
            FROM (
                SELECT DISTINCT ON (contact_id, channel) contact_id, occurred_at, channel
                FROM omni_send_outcomes
                WHERE contact_id IS NOT NULL AND status = 'sent'
                  AND (channel LIKE '%invite%' OR channel LIKE '%profile_view%')
                ORDER BY contact_id, channel, occurred_at
            ) collapsed_invites
            UNION ALL
            SELECT contact_id, occurred_at, channel,
                   'outbound'::text AS direction,
                   NULL AS snippet, NULL AS classification
            FROM omni_send_outcomes
            WHERE contact_id IS NOT NULL AND status = 'sent'
              AND channel NOT LIKE '%invite%' AND channel NOT LIKE '%profile_view%'
        )
        SELECT
            e.contact_id,
            c.first_name, c.last_name, c.company, c.headline,
            MAX(e.occurred_at)                                             AS last_message_at,
            COUNT(*)                                                       AS message_count,
            COUNT(*) FILTER (WHERE e.direction = 'inbound')                AS inbound_count,
            COUNT(*) FILTER (WHERE e.direction = 'outbound')               AS sent_count,
            MAX(e.occurred_at) FILTER (WHERE e.direction = 'inbound')      AS last_inbound_at,
            (ARRAY_AGG(e.channel ORDER BY e.occurred_at DESC))[1]          AS last_channel,
            (ARRAY_AGG(e.classification ORDER BY e.occurred_at DESC)
                 FILTER (WHERE e.classification IS NOT NULL))[1]           AS last_classification,
            (ARRAY_AGG(e.snippet ORDER BY e.occurred_at DESC)
                 FILTER (WHERE e.snippet IS NOT NULL))[1]                  AS last_snippet
        FROM engaged e
        JOIN omni_contacts c ON c.id = e.contact_id
        WHERE ($2::uuid IS NULL OR EXISTS (
            SELECT 1 FROM omni_leads l
            WHERE l.contact_id = e.contact_id AND l.workflow_id = $2
        ))
        GROUP BY e.contact_id, c.first_name, c.last_name, c.company, c.headline
        ORDER BY last_message_at DESC
        LIMIT $1
        """,
        limit,
        workflow_id,
    )
    return [InboxThread.model_validate(r) for r in rows]


@router.get(
    "/threads/{contact_id}",
    response_model=list[InboxMessage],
    summary="Fetch the full message history for one contact",
)
async def get_thread(
    contact_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current_workspace),
    limit: int = Query(200, ge=1, le=1000),
) -> list[InboxMessage]:
    """The real conversation for a contact.

    LinkedIn DMs are not stored with their body (the muscle emits ``send.outcome``,
    not ``message.sent``), so the actual thread lives in the Unipile chat. We fetch it
    ON-DEMAND when the thread is opened — both sides, real text — rather than polling
    it continuously (usage-light: one call per open, and the client caches it).
    Invites/connection-requests are separate connection events, not chat messages, so
    they render as special ``metadata.system`` bubbles from the send ledger. Email and
    other channels fall back to the stored ``omni_messages`` log.
    """
    workspace_id = str(ctx.workspace_id)
    out: list[InboxMessage] = []

    # 1. Live LinkedIn conversation (both sides, real bodies) from the Unipile chat.
    async with system_scope():
        chat = await fetch_one(
            "SELECT custom_fields->>'chat_id' AS chat_id FROM omni_leads "
            "WHERE contact_id = $1 AND COALESCE(custom_fields->>'chat_id','') <> '' "
            "ORDER BY updated_at DESC LIMIT 1",
            contact_id,
        )
    live_linkedin = False
    if chat and chat["chat_id"]:
        try:
            client = await UnipileClient.for_workspace(workspace_id)
            resp = await client.list_chat_messages(str(chat["chat_id"]), limit=min(limit, 100))
            items = resp.get("items") if isinstance(resp, dict) else resp
            # The chat carries the sending account; individual messages may not.
            account_id = ""
            if isinstance(resp, dict):
                account_id = str(resp.get("account_id") or "")
            if not account_id:
                chat_meta = await client.get_chat(str(chat["chat_id"]))
                account_id = str((chat_meta or {}).get("account_id") or "")
            for msg in reversed(items or []):  # Unipile returns newest-first
                if msg.get("is_event") or msg.get("deleted"):
                    continue
                text = msg.get("text") or ""
                if not text:
                    continue
                out.append(
                    InboxMessage(
                        id=uuid.uuid5(_UNIPILE_MSG_NS, str(msg.get("id") or uuid.uuid4())),
                        contact_id=contact_id,
                        channel="linkedin",
                        direction="outbound" if msg.get("is_sender") == 1 else "inbound",
                        subject=None,
                        body=text,
                        classification=None,
                        confidence=None,
                        # MSG-EDIT-002: the PROVIDER id is what /messages/{id}/edit
                        # needs. The InboxMessage id above is a derived uuid5 (a
                        # stable React key), so without carrying this the real
                        # message could never be addressed.
                        metadata={
                            "source": "unipile",
                            "provider_message_id": str(msg.get("id") or ""),
                            "account_id": str(msg.get("account_id") or account_id or ""),
                            "is_sender": msg.get("is_sender") == 1,
                            "provider_edited": bool(msg.get("edited")),
                        },
                        occurred_at=_parse_ts(msg.get("timestamp")),
                    )
                )
            live_linkedin = True
        except Exception as e:  # noqa: BLE001 — fail-soft to the stored log below
            log.warning("[inbox] live chat fetch failed for contact %s: %s", contact_id, e)

    # 2. Stored messages — keep non-LinkedIn (email/etc.); the live chat supersedes
    #    stored LinkedIn rows when we have it (avoids double-showing a captured reply).
    async with system_scope():
        stored = await fetch_all(
            "SELECT id, contact_id, channel, direction, subject, body, "
            "classification, confidence, metadata, occurred_at "
            "FROM omni_messages WHERE contact_id = $1 ORDER BY occurred_at ASC LIMIT $2",
            contact_id,
            limit,
        )
    for r in stored:
        if live_linkedin and str(r["channel"] or "").startswith("linkedin"):
            continue
        out.append(InboxMessage.model_validate(r))

    # 3. Invites/connection-requests (and any DM we couldn't pull live) as special
    #    bubbles from the send ledger.
    async with system_scope():
        sends = await fetch_all(
            "SELECT id, contact_id, channel, occurred_at, status FROM omni_send_outcomes "
            "WHERE contact_id = $1 AND status = 'sent' ORDER BY occurred_at ASC LIMIT $2",
            contact_id,
            limit,
        )
    seen_invite: set[str] = set()
    for r in sends:
        ch = str(r["channel"] or "")
        is_invite = "invite" in ch or "profile_view" in ch
        if not is_invite and live_linkedin and ch.startswith("linkedin"):
            continue  # the DM body already came from the live chat
        if is_invite:
            # A contact gets ONE connection request; multiple 'sent' rows are the
            # re-fire artifact (LinkedIn dedupes them). Collapse to a single bubble.
            if ch in seen_invite:
                continue
            seen_invite.add(ch)
        label = (
            "Connection request sent" if "invite" in ch
            else "Viewed profile" if "profile_view" in ch
            else "Message sent"
        )
        out.append(
            InboxMessage(
                id=r["id"],
                contact_id=contact_id,
                channel=ch,
                direction="outbound",
                subject=None,
                body=label,
                classification=None,
                confidence=None,
                metadata={"kind": "invite" if is_invite else "send", "system": True},
                occurred_at=r["occurred_at"],
            )
        )

    # 4. MSG-EDIT-001: overlay operator corrections. Applied LAST so it covers
    #    every source uniformly — live Unipile bubbles (whose bodies exist only
    #    at the provider) and stored omni_messages rows alike. The original text
    #    always rides along in metadata so the reader can see what was really
    #    sent; an edit annotates the record, it never silently replaces it.
    async with system_scope():
        edits = await fetch_all(
            "SELECT message_id, edited_body, original_body, reason, updated_at "
            "FROM omni_message_edits WHERE workspace_id=$1 AND contact_id=$2",
            workspace_id,
            contact_id,
        )
    if edits:
        by_id = {str(e["message_id"]): e for e in edits}
        for message in out:
            edit = by_id.get(str(message.id))
            if not edit:
                continue
            # The body is NOT overridden: the provider is the source of truth and
            # already returns the edited text. What we add is the provenance the
            # provider does not keep — what it said before, who changed it, when.
            message.metadata = {
                **(message.metadata or {}),
                "edited": True,
                "original_body": edit["original_body"],
                "edit_reason": edit["reason"],
                "edited_at": edit["updated_at"].isoformat(),
            }

    out.sort(key=lambda m: m.occurred_at)
    return out[-limit:] if len(out) > limit else out


class MessageEditIn(BaseModel):
    body: str = Field(min_length=1, max_length=20000, description="The corrected text")
    reason: str | None = Field(None, max_length=200, description="Why the record was corrected")


def _is_system_bubble(metadata: dict | None) -> bool:
    """Invite / profile-view / bare-send bubbles are LABELS the inbox renders from
    the send ledger ("Connection request sent"), not message text. Editing one
    would invent a message that never existed."""
    return bool((metadata or {}).get("system"))


@router.patch(
    "/threads/{contact_id}/messages/{message_id}",
    status_code=200,
    summary="Edit a sent message at the provider (MSG-EDIT-002)",
    description=(
        "Really edits the message on LinkedIn via Unipile — the recipient sees the "
        "new text, marked edited. LinkedIn only allows this for a limited period "
        "after sending; once that window closes the provider refuses and its reason "
        "is returned verbatim. Only your OWN outbound messages can be edited. "
        "The provider keeps no history, so the text before the edit is recorded "
        "locally with its author and timestamp; DELETE the same path edits it back."
    ),
)
async def edit_message(
    contact_id: uuid.UUID,
    message_id: uuid.UUID,
    body: MessageEditIn,
    ctx: AuthContext = Depends(get_current_workspace),
) -> dict[str, Any]:
    workspace_id = str(ctx.workspace_id)
    thread = await get_thread(contact_id, ctx=ctx, limit=1000)
    target = next((m for m in thread if str(m.id) == str(message_id)), None)
    if target is None:
        raise HTTPException(404, "message not found in this contact's thread")
    meta = target.metadata or {}
    if _is_system_bubble(meta):
        raise HTTPException(
            422,
            "that entry is a connection/send event rendered from the send ledger, "
            "not a message, so there is nothing to edit",
        )
    if target.direction != "outbound":
        raise HTTPException(422, "only your own outbound messages can be edited")
    provider_message_id = str(meta.get("provider_message_id") or "")
    account_id = str(meta.get("account_id") or "")
    if not provider_message_id or not account_id:
        raise HTTPException(
            422,
            "this message has no live provider handle (its body is not held at the "
            "provider), so it cannot be edited there",
        )

    # Edit at the provider FIRST. If LinkedIn's window has closed it refuses, and
    # recording a local 'edit' for a message the recipient still sees unchanged
    # would be a lie about what they are looking at.
    try:
        client = await UnipileClient.for_workspace(workspace_id)
        await client.edit_message(provider_message_id, body.body, account_id=account_id)
    except Exception as exc:  # noqa: BLE001 — surface the provider's own reason
        log.warning("MSG-EDIT-002: provider refused edit of %s: %s", provider_message_id, exc)
        raise HTTPException(
            422,
            f"LinkedIn refused the edit — the edit window for this message has most "
            f"likely closed. Provider said: {str(exc)[:200]}",
        ) from exc

    # The original is whatever the record said BEFORE any edit — so a second
    # edit must not overwrite it with the first edit's text.
    original = meta.get("original_body") or target.body or ""
    async with system_scope():
        await db_execute(
            """
            INSERT INTO omni_message_edits
                (workspace_id, message_id, contact_id, edited_body, original_body, reason, edited_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (workspace_id, message_id) DO UPDATE
                SET edited_body = EXCLUDED.edited_body,
                    reason      = EXCLUDED.reason,
                    edited_by   = EXCLUDED.edited_by,
                    updated_at  = NOW()
            """,
            workspace_id,
            str(message_id),
            str(contact_id),
            body.body,
            original,
            body.reason,
            ctx.user_id or None,
        )
    log.info(
        "MSG-EDIT-002: message %s (provider %s) on contact %s edited by %s",
        message_id, provider_message_id, contact_id, ctx.user_id,
    )
    return {"message_id": str(message_id), "edited": True, "original_body": original}


@router.delete(
    "/threads/{contact_id}/messages/{message_id}",
    status_code=200,
    summary="Put a message back to its original text",
    description=(
        "Edits the message at the provider back to the text it had before, then drops "
        "the local edit record. Subject to the same LinkedIn edit window as any other "
        "edit — this is a real edit back, not an undo."
    ),
)
async def revert_message_edit(
    contact_id: uuid.UUID,
    message_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current_workspace),
) -> dict[str, Any]:
    workspace_id = str(ctx.workspace_id)
    async with system_scope():
        row = await fetch_one(
            "SELECT original_body FROM omni_message_edits "
            "WHERE workspace_id=$1 AND message_id=$2 AND contact_id=$3",
            workspace_id, str(message_id), str(contact_id),
        )
    if row is None:
        raise HTTPException(404, "that message has no recorded edit to undo")

    thread = await get_thread(contact_id, ctx=ctx, limit=1000)
    target = next((m for m in thread if str(m.id) == str(message_id)), None)
    meta = (target.metadata if target else None) or {}
    provider_message_id = str(meta.get("provider_message_id") or "")
    account_id = str(meta.get("account_id") or "")
    if not provider_message_id or not account_id:
        raise HTTPException(422, "this message has no live provider handle to edit back")

    try:
        client = await UnipileClient.for_workspace(workspace_id)
        await client.edit_message(provider_message_id, row["original_body"], account_id=account_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            422,
            f"LinkedIn refused the edit back — the window has most likely closed, so "
            f"the recipient keeps the edited text. Provider said: {str(exc)[:200]}",
        ) from exc

    async with system_scope():
        await db_execute(
            "DELETE FROM omni_message_edits WHERE workspace_id=$1 AND message_id=$2 "
            "AND contact_id=$3",
            workspace_id, str(message_id), str(contact_id),
        )
    return {"message_id": str(message_id), "edited": False, "body": row["original_body"]}


@router.get(
    "/notifications",
    response_model=list[InboxNotification],
    summary="Recent inbound replies for the notifications bell (latest-first)",
)
async def list_notifications(
    _: AuthContext = Depends(get_current_workspace),
    limit: int = Query(20, ge=1, le=100),
) -> list[InboxNotification]:
    # Just the inbound replies, newest first, with the contact's name resolved. The
    # client compares occurred_at against a locally-stored "last seen" to compute the
    # unread badge — no server-side per-user read state needed for this.
    rows = await fetch_all(
        """
        SELECT m.id, m.contact_id, c.first_name, c.last_name, c.company,
               m.channel, LEFT(m.body, 160) AS snippet, m.classification, m.occurred_at
        FROM omni_messages m
        JOIN omni_contacts c ON c.id = m.contact_id
        WHERE m.direction = 'inbound' AND m.contact_id IS NOT NULL
        ORDER BY m.occurred_at DESC
        LIMIT $1
        """,
        limit,
    )
    return [InboxNotification.model_validate(r) for r in rows]


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

    # Resolve the real conversation context first. A manual reply must use the
    # same LinkedIn seat that sent the invite and the existing chat_id; otherwise
    # it can come from a stranger seat or open a second chat.
    async with system_scope():
        thread_lead = await fetch_one(
            "SELECT workflow_id, custom_fields FROM omni_leads "
            "WHERE workspace_id=$1 AND contact_id=$2 "
            "ORDER BY (status='waiting') DESC, updated_at DESC LIMIT 1",
            workspace_id,
            contact_id,
        )
    thread_cf: dict[str, Any] = {}
    workflow_id: str | None = None
    if thread_lead:
        workflow_id = str(thread_lead.get("workflow_id") or "") or None
        raw_cf = thread_lead.get("custom_fields") or {}
        if isinstance(raw_cf, str):
            try:
                raw_cf = json.loads(raw_cf)
            except (TypeError, ValueError):
                raw_cf = {}
        if isinstance(raw_cf, dict):
            thread_cf = raw_cf

    pinned_account_id: str | None = None
    invite_account_id = thread_cf.get("invite_account_id")
    if channel == ChannelType.LINKEDIN_DM and invite_account_id:
        async with system_scope():
            seat = await fetch_one(
                "SELECT id FROM omni_sending_accounts WHERE workspace_id=$1 "
                "AND channel_kind='linkedin' AND external_identity=$2 "
                "AND status IN ('active','warming') LIMIT 1",
                workspace_id,
                str(invite_account_id),
            )
        if seat:
            pinned_account_id = str(seat["id"])
    if not pinned_account_id:
        account_kind = _ACCOUNT_KIND_BY_CHANNEL.get(channel)
        async with system_scope():
            last_seat = await fetch_one(
                "SELECT o.sending_account_id FROM omni_send_outcomes o "
                "JOIN omni_sending_accounts sa ON sa.id=o.sending_account_id "
                "AND sa.workspace_id=o.workspace_id "
                "WHERE o.workspace_id=$1 AND o.contact_id=$2 AND o.status='sent' "
                "AND o.sending_account_id IS NOT NULL "
                "AND ($3::text IS NULL OR sa.channel_kind=$3) "
                "AND sa.status IN ('active','warming') "
                "ORDER BY o.occurred_at DESC LIMIT 1",
                workspace_id,
                contact_id,
                account_kind,
            )
        if last_seat:
            pinned_account_id = str(last_seat["sending_account_id"])

    if channel == ChannelType.LINKEDIN_DM and not pinned_account_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "the LinkedIn seat for this conversation is unavailable; reply blocked "
                "to prevent sending from the wrong account"
            ),
        )

    # Resolve the workspace connection for this channel's provider (fallback
    # only; a pinned seat causes build_command to load that seat's connection).
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

    # Synthesize a one-shot command context. Unlike the old black-hole path, a
    # durable queued ledger row is written BEFORE publish; transition_worker
    # recognizes node_id=inbox-reply and finalizes it without advancing a lead.
    correlation_id = str(uuid.uuid4())
    synthetic_lead: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "workflow_id": workflow_id,
        "contact_id": str(contact_id),
        "custom_fields": thread_cf,
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
        sending_account_id=pinned_account_id,
    )
    command_id = str(command["command_id"])
    resolved_account_id = (command.get("metadata") or {}).get("sending_account_id")
    await db_execute(
        "INSERT INTO omni_send_outcomes "
        "(workspace_id,lead_id,contact_id,workflow_id,node_id,channel,mode,"
        " sending_account_id,command_id,attempt,status,occurred_at) "
        "VALUES ($1,NULL,$2,$3,NULL,$4,'manual_reply',$5,$6,0,'queued',NOW()) "
        "ON CONFLICT (workspace_id,command_id,attempt) DO NOTHING",
        workspace_id,
        contact_id,
        workflow_id,
        channel.value,
        resolved_account_id,
        command_id,
    )
    try:
        await commands.publish_command(command)
    except Exception as exc:  # noqa: BLE001 — preserve a durable failed attempt
        await db_execute(
            "UPDATE omni_send_outcomes SET status='failed', error_code='COMMAND_PUBLISH_FAILED', "
            "error_detail=$1, occurred_at=NOW() WHERE workspace_id=$2 AND command_id=$3 AND attempt=0",
            str(exc)[:1000],
            workspace_id,
            command_id,
        )
        raise HTTPException(status_code=503, detail="reply could not be queued") from exc

    return ReplyAccepted(
        status="queued", channel=channel.value, correlation_id=uuid.UUID(correlation_id)
    )
