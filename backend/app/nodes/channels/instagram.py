"""Instagram DM channel node — Graph API via the muscle."""

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


class InstagramChannelConfig(BaseModel):
    connection_name: str | None = Field(None, description="Instagram connection name (Settings → Integrations)")
    sending_account_id: str | None = None
    account_pool: Literal["campaign", "round_robin", "single"] | None = None
    body_template: str = Field(min_length=1, max_length=1000, description="DM body; supports {{contact.first_name}} variables")


MANIFEST = NodeManifest(
    type="channel.instagram",
    category=NodeCategory.CHANNEL,
    summary="Send an Instagram DM via a workspace connection",
    config_schema=InstagramChannelConfig,
    output_handles=(
        NodeHandle("sent", "Graph API accepted the DM"),
        NodeHandle("on_error", "Permanent failure (outside messaging window, no handle, …)"),
    ),
    capabilities=("connection:instagram",),
    side_effect=SideEffect.NETWORK,
    icon="instagram",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = InstagramChannelConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "channel.instagram.queued",
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
