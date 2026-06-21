"""WhatsApp channel node — Twilio WhatsApp / Cloud API via the muscle."""

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


class WhatsAppChannelConfig(BaseModel):
    connection_name: str | None = Field(None, description="WhatsApp connection name (Settings → Integrations)")
    sending_account_id: str | None = None
    account_pool: Literal["campaign", "round_robin", "single"] | None = None
    body_template: str = Field(min_length=1, max_length=4096, description="Message body; supports {{contact.first_name}} variables")
    template_name: str | None = Field(None, description="Approved WhatsApp template name (required outside the 24h session window)")


MANIFEST = NodeManifest(
    type="channel.whatsapp",
    category=NodeCategory.CHANNEL,
    summary="Send a WhatsApp message via a workspace connection",
    config_schema=WhatsAppChannelConfig,
    output_handles=(
        NodeHandle("sent", "Provider accepted the message"),
        NodeHandle("on_error", "Permanent failure (no opt-in, invalid number, …)"),
    ),
    capabilities=("connection:whatsapp",),
    side_effect=SideEffect.NETWORK,
    icon="message-circle",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = WhatsAppChannelConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "channel.whatsapp.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "body_template": cfg.body_template,
                "template_name": cfg.template_name,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="sent", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
