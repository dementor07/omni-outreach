"""Telegram channel node — Bot API via the muscle."""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import Field

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


class TelegramChannelConfig(SendDedupeConfig):
    connection_name: str | None = Field(None, description="Telegram bot connection name (Settings → Integrations)")
    sending_account_id: str | None = None
    account_pool: Literal["campaign", "round_robin", "single"] | None = None
    body_template: str = Field(min_length=1, max_length=4096, description="Message body; supports {{contact.first_name}} variables")


MANIFEST = NodeManifest(
    type="channel.telegram",
    category=NodeCategory.CHANNEL,
    summary="Send a Telegram message via a workspace bot connection",
    config_schema=TelegramChannelConfig,
    output_handles=(
        NodeHandle("sent", "Bot API accepted the message"),
        NodeHandle("on_error", "Permanent failure (user has not started the bot, …)"),
        # DEDUP-SEND-001: contact already messaged on this channel — skipped, continue here.
        NodeHandle("already_messaged", "Skipped — this contact was already messaged"),
    ),
    capabilities=("connection:telegram",),
    side_effect=SideEffect.NETWORK,
    icon="send",
    can_be_entry=True,  # OUTBOUND-FIRST-001: can start a campaign against an audience
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = TelegramChannelConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "channel.telegram.queued",
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
