"""channel.linkedin_follow — follow a LinkedIn member (Unipile).

A per-lead social ACTION (real side effect) — gated like a message in a campaign.
Routes to ChannelType.LinkedinFollow. The member is resolved from the lead's
linkedin_url (or a provider_id in custom_fields) by the handler.
"""

from __future__ import annotations

import uuid

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


class LinkedInFollowConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection")
    unipile_account_id: str = Field(min_length=1, description="Unipile seat (account id)")


MANIFEST = NodeManifest(
    type="channel.linkedin_follow",
    category=NodeCategory.SINK,
    display_name="Follow LinkedIn member",
    summary="Follow a member from a seat (Unipile)",
    config_schema=LinkedInFollowConfig,
    output_handles=(
        NodeHandle("sent", "Follow posted"),
        NodeHandle("on_error", "Follow failed"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="user-plus",
    primary_fields=("connection_name", "unipile_account_id"),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInFollowConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    cf = ctx.lead.get("custom_fields") or {}
    return NodeResult(
        handle="sent",
        events=[
            {
                "event_type": "channel.linkedin_follow.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "unipile",
                    "connection_name": cfg.connection_name,
                    "unipile_account_id": cfg.unipile_account_id,
                    "provider_id": cf.get("provider_id"),
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "unipile"},
    )


register(MANIFEST, execute)
