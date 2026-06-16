"""Inbound webhook listener — the runtime half of source.webhook_in.

  POST /webhooks/in/{workflow_id}/{node_id}

An external system POSTs a JSON body here; for each accepted POST we:
  1. (optional) verify an HMAC signature in x-omni-signature against the
     workspace's webhook secret, when the node's config sets require_hmac;
  2. map the incoming JSON into contact fields via the node's field_map
     (dotted paths, e.g. {"email": "data.user.email"});
  3. emit contact.created, seed a lead positioned AT the webhook node, and
     emit a transition off the node's `default` handle so the new lead flows
     down the workflow.

This endpoint is intentionally UNAUTHENTICATED (no JWT) — external systems
can't carry a user token. Tenancy + trust come from: the opaque
{workflow_id}/{node_id} path (resolved to the owning workspace), the optional
HMAC, and the node having to exist and be a source.webhook_in. The workspace is
derived from the workflow row, never from the request.
"""

from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request

from app.config import settings
from app.db import execute, fetch_all, fetch_one, system_scope
from app.services import bus, reply_classifier

router = APIRouter()


def _resolve_path(obj: Any, path: str) -> Any:
    """Resolve a dotted path against a nested JSON object; None if any hop is
    missing or not a dict."""
    cur = obj
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
        if cur is None:
            return None
    return cur


def _verify_hmac(raw_body: bytes, signature: str | None) -> bool:
    """Constant-time HMAC-SHA256 check against the workspace webhook secret
    (UNIPILE_WEBHOOK_SECRET reused as the inbound signing secret). Signature is
    the hex digest in x-omni-signature."""
    secret = getattr(settings, "unipile_webhook_secret", "") or ""
    if not secret or not signature:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


@router.post(
    "/in/{workflow_id}/{node_id}",
    status_code=202,
    summary="Receive a contact from an external system (source.webhook_in)",
    description=(
        "Unauthenticated inbound webhook. Maps the JSON body to a contact via the "
        "node's field_map, creates a lead at the webhook node, and advances it "
        "into the workflow. Returns 202; projection + traversal are asynchronous."
    ),
)
async def receive_webhook(
    workflow_id: uuid.UUID,
    node_id: uuid.UUID,
    request: Request,
    x_omni_signature: str | None = Header(None),
) -> dict:
    raw = await request.body()

    # Resolve the node + its owning workspace from the opaque ids. system_scope
    # because there is no request workspace context (no JWT on this endpoint).
    async with system_scope():
        node = await fetch_one(
            """
            SELECT n.id, n.node_type, n.config, n.workspace_id, w.id AS workflow_id
            FROM omni_workflow_nodes n
            JOIN omni_workflows w ON w.id = n.workflow_id
            WHERE n.id = $1 AND n.workflow_id = $2
            """,
            node_id,
            workflow_id,
        )
    if not node or node["node_type"] != "source.webhook_in":
        raise HTTPException(status_code=404, detail="webhook endpoint not found")

    workspace_id = str(node["workspace_id"])
    cfg = node.get("config") or {}

    if cfg.get("require_hmac", True) and not _verify_hmac(raw, x_omni_signature):
        raise HTTPException(status_code=401, detail="invalid or missing webhook signature")

    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="body must be valid JSON") from e

    # Map incoming JSON -> contact fields via the node's field_map. Unmapped
    # standard fields fall back to top-level same-named keys.
    field_map: dict[str, str] = cfg.get("field_map") or {}
    contact_fields = ("email", "linkedin_url", "first_name", "last_name", "company", "headline", "phone")
    contact_payload: dict[str, Any] = {}
    for f in contact_fields:
        if f in field_map:
            contact_payload[f] = _resolve_path(body, field_map[f])
        elif isinstance(body.get(f), str):
            contact_payload[f] = body.get(f)
    if not contact_payload.get("email") and not contact_payload.get("linkedin_url"):
        raise HTTPException(status_code=422, detail="mapped payload has no email or linkedin_url")
    contact_payload["source"] = "webhook_in"

    contact_id = str(uuid.uuid4())
    lead_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())

    # 1. contact.created — the projector materialises omni_contacts.
    await bus.publish_event(
        workspace_id=workspace_id,
        event_type="contact.created",
        entity_type="contact",
        entity_id=contact_id,
        payload=contact_payload,
        correlation_id=correlation_id,
    )
    # 2. lead.created — seed a lead bound to the contact, positioned AT the
    #    webhook node so the transition below advances it to the next node.
    await bus.publish_event(
        workspace_id=workspace_id,
        event_type="lead.created",
        entity_type="lead",
        entity_id=lead_id,
        payload={
            "contact_id": contact_id,
            "workflow_id": str(workflow_id),
            "current_node_id": str(node_id),
            "status": "active",
        },
        correlation_id=correlation_id,
    )
    # 3. Advance the lead off the webhook node's `default` handle (same resume
    #    mechanism approvals uses). The transition worker finds the outgoing
    #    edge and fires the next node.
    transition = {
        "lead_id": lead_id,
        "source_node_id": str(node_id),
        "handle": "default",
        "event_type": "transition",
        "metadata": {"workspace_id": workspace_id, "correlation_id": correlation_id},
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    await bus._producer.send_and_wait(bus.TRANSITIONS_TOPIC, value=transition, key=lead_id)  # type: ignore[union-attr]

    return {"accepted": True, "contact_id": contact_id, "lead_id": lead_id}


@router.post(
    "/reply/{workspace_id}",
    status_code=202,
    summary="Receive an inbound reply (Unipile / email) — classify + wake the lead",
    description=(
        "Unauthenticated inbound reply webhook. Resolves the contact by "
        "email/linkedin, classifies the reply intent (B2: single LLM call + "
        "keyword fallback), records message.received with classification, "
        "auto-suppresses on unsubscribe, and wakes any lead waiting on that "
        "contact via a 'replied' transition. Returns 202."
    ),
)
async def receive_reply(
    workspace_id: uuid.UUID,
    request: Request,
    x_omni_signature: str | None = Header(None),
) -> dict:
    raw = await request.body()
    # HMAC required — inbound replies carry real recipient data.
    if not _verify_hmac(raw, x_omni_signature):
        raise HTTPException(status_code=401, detail="invalid or missing webhook signature")
    try:
        body = await request.json()
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="body must be valid JSON") from e

    ws = str(workspace_id)
    channel = (body.get("channel") or "email").strip()
    text = body.get("body") or body.get("text") or ""
    email = (body.get("email") or "").strip().lower() or None
    linkedin_url = (body.get("linkedin_url") or "").strip() or None
    if not email and not linkedin_url:
        raise HTTPException(status_code=422, detail="reply needs an email or linkedin_url to resolve the contact")

    # Resolve the contact within the workspace. system_scope: no JWT here, so
    # bind the tenant explicitly via the path workspace_id.
    async with system_scope():
        if email:
            contact = await fetch_one(
                "SELECT id FROM omni_contacts WHERE workspace_id=$1 AND lower(email)=$2 LIMIT 1",
                ws, email,
            )
        else:
            contact = await fetch_one(
                "SELECT id FROM omni_contacts WHERE workspace_id=$1 AND linkedin_url=$2 LIMIT 1",
                ws, linkedin_url,
            )
    if not contact:
        # Nothing to attach the reply to — accept but no-op (idempotent for retries).
        return {"accepted": True, "matched": False}
    contact_id = str(contact["id"])
    correlation_id = str(uuid.uuid4())

    # B2 — classify intent (one LLM call, keyword fallback).
    intent, confidence, reason, source = await reply_classifier.classify_reply(ws, text)

    # message.received — the projector persists it with classification/confidence.
    await bus.publish_event(
        workspace_id=ws,
        event_type="message.received",
        entity_type="message",
        entity_id=str(uuid.uuid4()),
        payload={
            "contact_id": contact_id,
            "channel": channel,
            "subject": body.get("subject"),
            "body": text,
            "classification": intent,
            "confidence": confidence,
            "metadata": {"reason": reason, "classifier_source": source},
        },
        correlation_id=correlation_id,
    )

    # T1 tie-in — an unsubscribe auto-writes the suppression list so this contact
    # is never messaged again on any channel.
    if intent == "unsubscribe":
        async with system_scope():
            if email:
                await execute(
                    "INSERT INTO omni_suppression_list (workspace_id, kind, value, reason, source) "
                    "VALUES ($1, 'email', $2, 'reply unsubscribe', 'unsubscribe') "
                    "ON CONFLICT (workspace_id, kind, value) DO NOTHING",
                    ws, email,
                )
            if linkedin_url:
                await execute(
                    "INSERT INTO omni_suppression_list (workspace_id, kind, value, reason, source) "
                    "VALUES ($1, 'linkedin', $2, 'reply unsubscribe', 'unsubscribe') "
                    "ON CONFLICT (workspace_id, kind, value) DO NOTHING",
                    ws, linkedin_url.lower(),
                )

    # SM-8 reply→wake-up — wake any lead for this contact that is parked
    # 'waiting' at a node, off the 'replied' handle so a condition.replied /
    # flow.race branch can react. The transition worker resolves the edge.
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
        await bus._producer.send_and_wait(bus.TRANSITIONS_TOPIC, value=transition, key=str(lead["id"]))  # type: ignore[union-attr]

    return {
        "accepted": True,
        "matched": True,
        "contact_id": contact_id,
        "intent": intent,
        "confidence": confidence,
        "source": source,
        "woke_leads": len(waiting),
    }
