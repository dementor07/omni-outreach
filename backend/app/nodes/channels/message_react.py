"""channel.message_react — react to a message in a chat (Unipile).

A per-lead social ACTION (real side effect) — gated like a message in a campaign.
Routes to ChannelType.MessageReact. The target message id comes from
custom_fields (e.g. the last inbound message the inbox recorded).
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


class MessageReactConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection")
    unipile_account_id: str = Field(min_length=1, description="Unipile seat (account id)")
    message_id_field: str = Field("last_message_id", description="custom_fields key holding the target message id")
    reaction: str = Field("👍", description="Emoji reaction to apply")


MANIFEST = NodeManifest(
    type="channel.message_react",
    category=NodeCategory.SINK,
    display_name="React to message",
    summary="React to a message in a chat from a seat (Unipile)",
    config_schema=MessageReactConfig,
    output_handles=(
        NodeHandle("sent", "Reaction applied"),
        NodeHandle("on_error", "Reaction failed"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="smile",
    primary_fields=("connection_name", "unipile_account_id", "reaction"),
    advanced_fields=("message_id_field",),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = MessageReactConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    cf = ctx.lead.get("custom_fields") or {}
    message_id = cf.get(cfg.message_id_field) or ctx.config.get("message_id")
    return NodeResult(
        handle="sent",
        events=[
            {
                "event_type": "channel.message_react.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "unipile",
                    "connection_name": cfg.connection_name,
                    "unipile_account_id": cfg.unipile_account_id,
                    "message_id": message_id,
                    "reaction": cfg.reaction,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "unipile"},
    )


register(MANIFEST, execute)
