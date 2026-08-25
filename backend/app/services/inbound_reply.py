"""Shared inbound-reply processing — the ONE implementation of the SM-8 contract.

An inbound reply (LinkedIn DM, WhatsApp, email) does the same four things no
matter how we learned about it:

  1. classify the reply intent (B2 — keyword classifier; opt-out always caught);
  2. record ``message.received`` (idempotent on the source message id when one
     is available, so the same reply never double-logs);
  3. auto-suppress the contact on an unsubscribe/opt-out (compliance — never
     message them again on any channel);
  4. wake every lead parked ``waiting`` for that contact off the ``replied``
     handle, so a ``condition.replied`` / ``flow.race`` branch halts the
     sequence (no follow-up after a human answered).

Both the Unipile push webhook (``routers/webhooks_in``) and the reply POLLER
(``execution/unipile_sync_worker``) call this. The push proved structurally
unreliable for LinkedIn — Unipile's ``message_received`` payload does not carry
the sender's profile URL our handler keyed on, so the contact never resolved and
no lead woke even though the webhook fired — so the poller is the PRIMARY
detector and MUST behave identically. Keeping one implementation guarantees it.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.db import execute, fetch_all, fetch_one, system_scope
from app.services import bus, reply_classifier

# Deterministic namespace for message.received event ids derived from a provider
# message id — lets a redelivered/re-polled reply collapse to one omni_messages
# row (the projector keys on the event id, ON CONFLICT (id) DO NOTHING).
_MSG_EVENT_NS = uuid.UUID("6f0e4a1c-3d2b-4f5a-8c7e-1a2b3c4d5e6f")


async def resolve_contact_by_linkedin(ws: str, linkedin_url: str) -> str | None:
    """Contact id for a LinkedIn URL within the workspace, or None."""
    async with system_scope():
        row = await fetch_one(
            "SELECT id FROM omni_contacts WHERE workspace_id=$1 AND linkedin_url=$2 LIMIT 1",
            ws, linkedin_url,
        )
    return str(row["id"]) if row else None


async def _resolve_campaign(ws: str, contact_id: str) -> str | None:
    """MSG-CAMPAIGN-001 — which campaign does this inbound reply belong to?

    A contact can sit in several campaigns at once, so there is no single
    ``contact -> campaign`` answer. The reply is attributed to whoever last SENT
    to them: a reply belongs to the conversation that prompted it, and the most
    recent outbound touch IS that conversation. Where there is no send history
    (a reply to a message that predates outcome tracking), a contact belonging
    to exactly ONE campaign takes that campaign.

    Returns None when nothing separates the candidates. That is deliberate --
    the column is nullable so an unattributable reply stays visibly
    unattributed instead of inflating whichever campaign sorted first.
    """
    async with system_scope():
        last_send = await fetch_one(
            """
            SELECT workflow_id FROM omni_send_outcomes
             WHERE workspace_id = $1 AND contact_id = $2 AND workflow_id IS NOT NULL
             ORDER BY occurred_at DESC
             LIMIT 1
            """,
            ws, contact_id,
        )
        if last_send and last_send.get("workflow_id"):
            return str(last_send["workflow_id"])
        sole = await fetch_one(
            """
            SELECT (array_agg(DISTINCT workflow_id))[1] AS workflow_id FROM omni_leads
             WHERE workspace_id = $1 AND contact_id = $2 AND workflow_id IS NOT NULL
            HAVING COUNT(DISTINCT workflow_id) = 1
            """,
            ws, contact_id,
        )
    return str(sole["workflow_id"]) if sole and sole.get("workflow_id") else None


async def process_reply(
    ws: str,
    contact_id: str,
    text: str,
    *,
    channel: str = "linkedin",
    source_message_id: str | None = None,
    correlation_id: str | None = None,
    occurred_at: str | None = None,
) -> dict:
    """Classify + record + suppress + wake for one inbound reply from ``contact_id``.

    ``source_message_id`` (the provider's message id) makes the ``message.received``
    write idempotent; omit it when there is no stable id (the event gets a random
    id, i.e. current webhook behaviour). Returns ``{intent, confidence, woke_leads}``.
    """
    correlation_id = correlation_id or str(uuid.uuid4())
    intent, confidence, reason, source = reply_classifier.classify_reply(text)
    # Resolve the campaign BEFORE publishing so the projector can stamp it
    # onto the row; the event payload is the only channel it has.
    workflow_id = await _resolve_campaign(ws, contact_id)

    # 1+2. message.received — build the envelope by hand so we can pin a
    # deterministic id when we have a provider message id (dedupe on redelivery /
    # re-poll). Shape must match what bus.publish_event produces.
    event_id = (
        str(uuid.uuid5(_MSG_EVENT_NS, f"{ws}:{source_message_id}"))
        if source_message_id
        else str(uuid.uuid4())
    )
    await bus.publish_events(
        [
            {
                "id": event_id,
                "workspace_id": ws,
                "event_type": "message.received",
                "entity_type": "message",
                "entity_id": str(uuid.uuid4()),
                "payload": {
                    "contact_id": contact_id,
                    "workflow_id": workflow_id,
                    "channel": channel,
                    "body": text,
                    "classification": intent,
                    "confidence": confidence,
                    "metadata": {"reason": reason, "classifier_source": source},
                },
                "actor_user_id": None,
                "correlation_id": correlation_id,
                # INBOX-TIME-001: when the provider tells us when they actually
                # replied, use it. Stamping ingestion time made a five-day-old
                # reply sort to the top of the inbox as if it had just arrived.
                "occurred_at": occurred_at or datetime.now(UTC).isoformat(),
            }
        ]
    )

    # 3. Auto-suppress on opt-out — look up the contact's identifiers so an
    #    'unsubscribe'/'stop' reply is honoured on every channel (T1). The
    #    LinkedIn push path historically skipped this; centralising fixes it.
    if intent == "unsubscribe":
        async with system_scope():
            ident = await fetch_one(
                "SELECT email, linkedin_url FROM omni_contacts WHERE id=$1 AND workspace_id=$2",
                contact_id, ws,
            )
        email = (ident or {}).get("email")
        linkedin_url = (ident or {}).get("linkedin_url")
        async with system_scope():
            if email:
                await execute(
                    "INSERT INTO omni_suppression_list (workspace_id, kind, value, reason, source) "
                    "VALUES ($1, 'email', $2, 'reply unsubscribe', 'unsubscribe') "
                    "ON CONFLICT (workspace_id, kind, value) DO NOTHING",
                    ws, email.lower(),
                )
            if linkedin_url:
                await execute(
                    "INSERT INTO omni_suppression_list (workspace_id, kind, value, reason, source) "
                    "VALUES ($1, 'linkedin', $2, 'reply unsubscribe', 'unsubscribe') "
                    "ON CONFLICT (workspace_id, kind, value) DO NOTHING",
                    ws, linkedin_url.lower(),
                )

    # 4. Wake every lead parked 'waiting' for this contact off the 'replied'
    #    handle. An unwired 'replied' handle is a leaf → the transition worker
    #    terminalizes the lead (completed@ended), which is exactly the halt a
    #    reply should cause when the campaign has no reply branch.
    async with system_scope():
        waiting = await fetch_all(
            "SELECT id, current_node_id FROM omni_leads "
            "WHERE workspace_id=$1 AND contact_id=$2 AND status='waiting' AND current_node_id IS NOT NULL",
            ws, contact_id,
        )
    for lead in waiting:
        transition = {
            "lead_id": str(lead["id"]),
            "source_node_id": str(lead["current_node_id"]),
            "handle": "replied",
            "event_type": "transition",
            "metadata": {"workspace_id": ws, "correlation_id": correlation_id, "reply_intent": intent},
            "occurred_at": datetime.now(UTC).isoformat(),
        }
        await bus._producer.send_and_wait(  # type: ignore[union-attr]
            bus.TRANSITIONS_TOPIC, value=transition, key=str(lead["id"])
        )

    return {"intent": intent, "confidence": confidence, "woke_leads": len(waiting)}
