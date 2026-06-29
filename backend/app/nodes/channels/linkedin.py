"""LinkedIn channel node — invite / DM / profile-view / InMail via Unipile.

Operators pick one ``mode`` on the node config; the Rust muscle's Unipile
handlers route by command channel. This node only validates config and
queues the action; the muscle owns the network call.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)
from app.nodes.channels.dedupe import SendDedupeConfig


class LinkedInChannelConfig(SendDedupeConfig):
    connection_name: str | None = Field(None, description="Unipile connection name (Settings → Integrations)")
    sending_account_id: str | None = None
    account_pool: Literal["campaign", "round_robin", "single"] | None = None
    mode: Literal["invite", "dm", "profile_view", "inmail"] = Field(description="Which LinkedIn action to perform")
    message_template: str | None = Field(None, description="Required for invite/dm/inmail; supports {{contact.first_name}}-style variables")
    subject_template: str | None = Field(None, description="Required only for inmail")


MANIFEST = NodeManifest(
    type="channel.linkedin",
    category=NodeCategory.CHANNEL,
    summary="LinkedIn invite, DM, profile-view, or InMail via Unipile",
    config_schema=LinkedInChannelConfig,
    output_handles=(
        NodeHandle("sent", "Action accepted by Unipile"),
        NodeHandle("on_error", "Permanent failure (account limit, blocked profile, …)"),
        # SMART-INVITE-001: an invite to an existing 1st-degree connection is
        # skipped and routed here so the sequence navigates straight to the next
        # step (no redundant invite, no parking at await-acceptance).
        NodeHandle("already_connected", "Invite skipped — recipient is already a connection"),
        # RELGATE-001: a DM to a non-1st-degree connection is held here instead
        # of burning a 403.
        NodeHandle("not_connected", "DM held — recipient is not a connection yet"),
        # NOCHAT-001: a DM opened a chat but Unipile returned no chat_id — the
        # send happened but the thread can't be followed up; degraded path.
        NodeHandle("no_thread", "DM sent but no chat thread to follow up on"),
        # DEDUP-SEND-001: this contact was already messaged on this channel (per
        # the node's dedupe_action/scope) — the send was skipped, continue here.
        NodeHandle("already_messaged", "Skipped — this contact was already messaged"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="linkedin",
    # OUTBOUND-FIRST-001: a LinkedIn outreach can START a campaign against an
    # attached audience (invite/DM a known list), not only follow a source.
    can_be_entry=True,
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInChannelConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": f"channel.linkedin.{cfg.mode}.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "mode": cfg.mode,
                "message_template": cfg.message_template,
                "subject_template": cfg.subject_template,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="sent", events=events, telemetry={"correlation_id": correlation_id, "mode": cfg.mode})


register(MANIFEST, execute)
