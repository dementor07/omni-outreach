"""Build an ActionCommand for a canvas node and publish it to the muscle.

The dispatcher and transition worker both call ``dispatch_node`` to fire the
node a lead currently sits on. This module owns:

  - node type  -> ChannelType            (which muscle handler runs)
  - node config + lead -> command payload (rendered, self-contained)
  - connection name -> one-shot credential_ref (secret never in the payload)

A node whose ``side_effect`` is not NETWORK/MUTATE (conditions, delays) has no
muscle command — the orchestrator advances it via its returned handle without a
muscle round-trip. Those are handled by the dispatcher directly, not here.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.config import settings
from app.core.events import ChannelType
from app.db import fetch_one, system_scope
from app.execution.render import render_channel_payload
from app.services import bus
from app.services.email_tracking import make_token
from app.services.encryption import decrypt

log = logging.getLogger(__name__)

# Node type -> muscle channel. Only side-effecting nodes appear here; anything
# absent is resolved locally by the dispatcher (conditions/flow) instead of
# being sent to the muscle.
NODE_CHANNEL: dict[str, ChannelType] = {
    "channel.email": ChannelType.EMAIL,
    "channel.sms": ChannelType.SMS,
    "channel.voice": ChannelType.VOICE,
    "channel.linkedin": ChannelType.LINKEDIN_DM,
    "channel.whatsapp": ChannelType.WHATSAPP,
    "channel.instagram": ChannelType.INSTAGRAM,
    "channel.telegram": ChannelType.TELEGRAM,
    "channel.slack": ChannelType.WEBHOOK,
    "channel.webhook_out": ChannelType.WEBHOOK,
    "crm.add_tag": ChannelType.ADD_TAG,
    "crm.remove_tag": ChannelType.REMOVE_TAG,
    "crm.hot_lead_alert": ChannelType.HOT_LEAD_ALERT,
    "ai.enrich": ChannelType.ENRICH,
    "ai.compose": ChannelType.AI_COMPOSE,
    # Claude classifier handler — both screen variants share it. The asymmetric
    # error policy lives in the node's payload (on_error_handle), not here.
    "ai.screen_company": ChannelType.AI_SCREEN,
    "ai.screen_person": ChannelType.AI_SCREEN,
    # Apify-driven LinkedIn jobs source (multi-step actor protocol).
    "source.linkedin_jobs": ChannelType.APIFY,
    # Camoufox-driven Naukri.com jobs source (anti-detect headless scrape).
    "source.naukri": ChannelType.NAUKRI,
    # Apify-driven Indeed.com jobs source (curious_coder/indeed-scraper actor).
    "source.indeed": ChannelType.INDEED,
    # Per-company people search (multi-pattern x titles, dedupe) — two distinct
    # nodes (paid Serper / free SearXNG), shared Rust handler.
    "source.serper_people": ChannelType.SERPER_PEOPLE,
    "source.searxng_people": ChannelType.SEARXNG_PEOPLE,
    # Company discovery — Auto-Pilot Target Mining. Four distinct sources, each
    # its own product/setup, NOT a provider toggle (handlers/discovery.rs).
    "source.searxng": ChannelType.SEARXNG,
    "source.serper_search": ChannelType.SERPER_SEARCH,
    "source.apollo": ChannelType.APOLLO,
    "source.clutch": ChannelType.CLUTCH,
    # ATS job-board sources — 12 distinct nodes, one shared muscle channel
    # (ChannelType.ATS); the muscle keys on payload.platform. All keyless.
    "source.greenhouse": ChannelType.ATS,
    "source.ashby": ChannelType.ATS,
    "source.smartrecruiters": ChannelType.ATS,
    "source.bamboohr": ChannelType.ATS,
    "source.workday": ChannelType.ATS,
    "source.icims": ChannelType.ATS,
    "source.lever": ChannelType.ATS,
    "source.workable": ChannelType.ATS,
    "source.recruitee": ChannelType.ATS,
    "source.personio": ChannelType.ATS,
    "source.rippling": ChannelType.ATS,
    "source.breezy": ChannelType.ATS,
    # Every declarative HTTP node (sources built via http_node) routes to the
    # generic handler. The dispatcher detects these by the emitted intent
    # carrying channel="http_call".
    "__http_call__": ChannelType.HTTP_CALL,
}

# Provider tag (from the node manifest capability "connection:<provider>")
# used to look up the workspace connection that holds the secret.
_CHANNEL_PROVIDER: dict[ChannelType, str] = {
    ChannelType.EMAIL: "smtp",
    ChannelType.SMS: "twilio",
    ChannelType.VOICE: "retell",
    ChannelType.LINKEDIN_DM: "unipile",
    ChannelType.WHATSAPP: "unipile",
    ChannelType.INSTAGRAM: "unipile",
    ChannelType.TELEGRAM: "unipile",
}


async def _load_connection_bundle(workspace_id: str, connection_name: str | None) -> dict[str, Any] | None:
    """Decrypt a workspace connection's credential bundle by name.
    Returns None when the node declares no connection (e.g. inline webhook)."""
    if not connection_name:
        return None
    async with system_scope():
        row = await fetch_one(
            "SELECT credentials_encrypted FROM omni_connections WHERE workspace_id=$1 AND name=$2",
            workspace_id,
            connection_name,
        )
    if not row:
        log.warning("[dispatch] no connection %r for workspace %s", connection_name, workspace_id)
        return None
    return json.loads(decrypt(row["credentials_encrypted"]))


async def _mint_credential_ref(bundle: dict[str, Any] | None, channel: str) -> str | None:
    """Persist the bundle as a one-shot credential ref the muscle redeems."""
    if bundle is None:
        return None
    # mint_credential_ref persists the encrypted bundle and returns the ref.
    from app.routers.internal import mint_credential_ref

    return await mint_credential_ref(channel, bundle)


def _lead_context(lead: dict[str, Any], contact: dict[str, Any] | None) -> dict[str, Any]:
    """The wire-shape the Rust muscle deserializes as LeadContext (models.rs).

    CONTRACT-1: every Option field the Rust struct declares should be honestly
    populated when the data exists — previously headline/source and the social
    chat-session fields were simply never sent, so the muscle always saw None.
    Chat-session ids (chat_id/ig_chat_id/tg_chat_id) live in the LEAD's
    custom_fields (written back by _apply_lead_mutations when send_chat opens a
    chat); usernames/location come from the contact's custom_fields."""
    c = contact or {}
    lead_cf = lead.get("custom_fields") or {}
    if isinstance(lead_cf, str):
        lead_cf = json.loads(lead_cf)
    contact_cf = c.get("custom_fields") or {}
    if isinstance(contact_cf, str):
        contact_cf = json.loads(contact_cf)
    return {
        "id": str(lead["id"]),
        "campaign_id": str(lead.get("workflow_id") or lead["id"]),
        "email": c.get("email"),
        "linkedin_url": c.get("linkedin_url"),
        "phone": c.get("phone"),
        "first_name": c.get("first_name"),
        "last_name": c.get("last_name"),
        "company": c.get("company"),
        "headline": c.get("headline"),
        "location": contact_cf.get("location"),
        "source": c.get("source"),
        "chat_id": lead_cf.get("chat_id"),
        "ig_chat_id": lead_cf.get("ig_chat_id"),
        "tg_chat_id": lead_cf.get("tg_chat_id"),
        "instagram_username": contact_cf.get("instagram_username"),
        "telegram_username": contact_cf.get("telegram_username"),
        "extra_data": lead_cf,
    }


async def build_command(
    *,
    workspace_id: str,
    channel: ChannelType,
    lead: dict[str, Any],
    contact: dict[str, Any] | None,
    node_id: str,
    payload: dict[str, Any],
    connection_name: str | None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Assemble the ActionCommand envelope the muscle consumes."""
    bundle = await _load_connection_bundle(workspace_id, connection_name)
    credential_ref = await _mint_credential_ref(bundle, channel.value)
    # T3: for email, mint a signed open/click tracking token so render injects
    # the pixel + link rewrites. Keyed to this workspace/lead/contact so the
    # public endpoints can attribute a hit without trusting the caller.
    tracking_base: str | None = None
    tracking_token: str | None = None
    if channel == ChannelType.EMAIL:
        tracking_base = settings.get_public_base_url()
        tracking_token = make_token(
            settings.secret_key,
            workspace_id=workspace_id,
            lead_id=str(lead["id"]) if lead.get("id") else None,
            contact_id=str(contact.get("id")) if contact and contact.get("id") else None,
        )
    # CONTRACT-2: fulfil the Rust handlers' self-contained-payload contract —
    # render *_template fields, copy non-secret transport/sender config from
    # the connection bundle, resolve the per-channel attendee identity, and
    # reuse persisted chat sessions. Without this every channel send starved.
    payload = render_channel_payload(
        channel, payload, lead=lead, contact=contact, bundle=bundle,
        tracking_base=tracking_base, tracking_token=tracking_token,
    )
    return {
        "command_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "channel": channel.value,
        "lead": _lead_context(lead, contact),
        "payload": payload,
        "credential_ref": credential_ref,
        "metadata": {
            "workspace_id": workspace_id,
            "node_id": node_id,
            "correlation_id": correlation_id or str(uuid.uuid4()),
        },
        "occurred_at": datetime.now(UTC).isoformat(),
    }


async def publish_command(command: dict[str, Any]) -> None:
    """Send the assembled command to the muscle, keyed by lead id for ordering."""
    await bus.publish_command(command, key=command["lead"]["id"])
