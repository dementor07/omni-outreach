"""channel.linkedin_react_post — react to / like a LinkedIn post (Unipile).

A per-lead social ACTION: it's a real outbound side effect, so when fired in a
campaign it passes the same send gates (DNC/dedupe/rate) as a message —
transition_worker routes it through _gate_send because it's registered in
_OUTBOUND_SEND_CHANNELS. Routes to ChannelType.LinkedinReactPost.
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


class LinkedInReactPostConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection")
    unipile_account_id: str = Field(min_length=1, description="Unipile seat (account id)")
    post_id_field: str = Field("post_id", description="custom_fields key holding the target post id")
    reaction: Literal["like", "celebrate", "support", "love", "insightful", "funny"] = Field("like")


MANIFEST = NodeManifest(
    type="channel.linkedin_react_post",
    category=NodeCategory.SINK,
    display_name="React to LinkedIn post",
    summary="Like/react to a LinkedIn post from a seat (Unipile)",
    config_schema=LinkedInReactPostConfig,
    output_handles=(
        NodeHandle("sent", "Reaction posted"),
        NodeHandle("on_error", "Reaction failed"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="thumbs-up",
    primary_fields=("connection_name", "unipile_account_id", "reaction"),
    advanced_fields=("post_id_field",),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInReactPostConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    cf = ctx.lead.get("custom_fields") or {}
    post_id = cf.get(cfg.post_id_field) or ctx.config.get("post_id")
    return NodeResult(
        handle="sent",
        events=[
            {
                "event_type": "channel.linkedin_react_post.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "unipile",
                    "connection_name": cfg.connection_name,
                    "unipile_account_id": cfg.unipile_account_id,
                    "post_id": post_id,
                    "reaction": cfg.reaction,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "unipile"},
    )


register(MANIFEST, execute)
