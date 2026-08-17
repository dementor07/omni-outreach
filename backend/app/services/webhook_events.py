"""Outbound webhook event vocabulary + signed delivery (N8N-001 Part 2).

Shared by the fan-out worker (webhook_dispatch_worker) and the subscription
`/test` endpoint. Owns:

  * ``ALLOWED_EVENTS`` — the fixed allow-list of customer-facing event names we
    will EVER deliver. Internal spine facts (transition, result_task, send.outcome,
    pipeline.metric, …) are never leaked. Each customer-facing name maps FROM the
    real fact the system emits today (see ``map_fact`` — grepped, not guessed):
      - lead.replied       <- message.received (an inbound reply was classified)
      - invite.accepted    <- lead-park resume on the invite_accepted signal is a
                              transition, not a fact; the durable fact is emitted
                              by the Unipile webhook as message.received/relation —
                              we surface it under the customer name invite.accepted
                              when the resume fires (see webhook_dispatch_worker).
      - campaign.run.completed <- campaign.run.completed (emitted verbatim by the
                              transition worker).
      - lead.enriched      <- lead.custom_fields_updated / ai.enrich completion
                              (surfaced under lead.enriched).
      - lead.hot           <- crm.hot_lead_alert.queued (a hot-lead alert fired).

  * ``normalize_envelope`` — the on-the-wire JSON envelope every delivery carries.
  * ``sign`` / ``deliver_one`` — HMAC-sign the body and POST it, SSRF-guarded.

The real fact names were grepped from the codebase; if a fact is later renamed,
update ``_FACT_TO_EVENT`` here (one place) — do NOT hardcode fact names in the
worker.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from app.services.url_guard import UnsafeURLError, validate_outbound_url

log = logging.getLogger(__name__)

# Customer-facing event names (the ONLY names we ever deliver).
ALLOWED_EVENTS: frozenset[str] = frozenset(
    {
        "lead.replied",
        "invite.accepted",
        "campaign.run.completed",
        "lead.enriched",
        "lead.hot",
        # ping is delivered only by the /test endpoint, never fanned out from a fact.
        "ping",
    }
)

# Real emitted fact name -> customer-facing event name. Grepped from the codebase
# (routers/webhooks_in.py message.received; transition_worker campaign.run.completed;
# crm/hot_lead_alert.py crm.hot_lead_alert.queued; verify_person/enrich mutations).
# A fact NOT in this map is never delivered (internal spine event).
_FACT_TO_EVENT: dict[str, str] = {
    "message.received": "lead.replied",
    "campaign.run.completed": "campaign.run.completed",
    "crm.hot_lead_alert.queued": "lead.hot",
    "lead.converted": "lead.hot",
    "lead.custom_fields_updated": "lead.enriched",
    "invite.accepted": "invite.accepted",
}


def map_fact(event_type: str) -> str | None:
    """The customer-facing event name for a raw fact, or None if not deliverable."""
    return _FACT_TO_EVENT.get(event_type)


def normalize_envelope(
    *, event: str, workspace_id: str, data: dict[str, Any], occurred_at: str | None = None
) -> dict[str, Any]:
    """The stable JSON shape every outbound delivery carries."""
    return {
        "event": event,
        "workspace_id": workspace_id,
        "occurred_at": occurred_at or datetime.now(UTC).isoformat(),
        "data": data,
    }


def sign(secret: str, body: bytes) -> str:
    """The ``X-Omni-Signature`` value: ``sha256=<hex hmac>`` over the raw body."""
    digest = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def serialize(envelope: dict[str, Any]) -> bytes:
    """Deterministic body bytes so the signature the receiver computes matches."""
    return json.dumps(envelope, separators=(",", ":"), sort_keys=True).encode("utf-8")


async def deliver_one(
    *,
    url: str,
    secret: str,
    event: str,
    workspace_id: str,
    data: dict[str, Any],
    occurred_at: str | None = None,
    timeout_s: float = 10.0,
) -> tuple[int | None, str | None]:
    """Sign + POST one envelope. Returns ``(status_code, error)``.

    SSRF-guarded at send (a hostname can re-resolve to a private IP between
    create and delivery). Never raises — a delivery failure returns an error
    string so the worker can record it and move on."""
    try:
        validate_outbound_url(url, resolve=True)
    except UnsafeURLError as e:
        return None, f"blocked unsafe URL: {e}"

    envelope = normalize_envelope(event=event, workspace_id=workspace_id, data=data, occurred_at=occurred_at)
    body = serialize(envelope)
    signature = sign(secret, body)
    headers = {
        "Content-Type": "application/json",
        "X-Omni-Signature": signature,
        "X-Omni-Event": event,
    }
    try:
        async with httpx.AsyncClient(timeout=timeout_s, follow_redirects=False) as client:
            resp = await client.post(url, content=body, headers=headers)
        return resp.status_code, None if resp.is_success else f"HTTP {resp.status_code}"
    except httpx.HTTPError as e:
        return None, f"network error: {e}"
