"""SMS channel node — Twilio via the Rust muscle's handle_sms."""

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


class SmsChannelConfig(SendDedupeConfig):
    connection_name: str | None = Field(None, description="Twilio connection name (Settings → Integrations)")
    sending_account_id: str | None = None
    account_pool: Literal["campaign", "round_robin", "single"] | None = None
    body_template: str = Field(min_length=1, max_length=1600, description="Message body; supports {{contact.first_name}}-style variables")


MANIFEST = NodeManifest(
    type="channel.sms",
    category=NodeCategory.CHANNEL,
    summary="Send an SMS via a workspace Twilio connection",
    config_schema=SmsChannelConfig,
    output_handles=(
        NodeHandle("sent", "Twilio accepted the message"),
        NodeHandle("on_error", "Permanent failure (invalid number, no credit, …)"),
        # DEDUP-SEND-001: contact already messaged on this channel — skipped, continue here.
        NodeHandle("already_messaged", "Skipped — this contact was already messaged"),
    ),
    capabilities=("connection:twilio",),
    side_effect=SideEffect.NETWORK,
    icon="message-square",
    can_be_entry=True,  # OUTBOUND-FIRST-001: can start a campaign against an audience
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = SmsChannelConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "channel.sms.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "body_template": cfg.body_template,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="sent", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
