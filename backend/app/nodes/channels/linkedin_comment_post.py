"""channel.linkedin_comment_post — comment on a LinkedIn post (Unipile).

A per-lead social ACTION (real side effect) — gated like a message in a campaign.
Routes to ChannelType.LinkedinCommentPost. The comment text renders from
``comment_template`` (or a static ``comment``).
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


class LinkedInCommentPostConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection")
    unipile_account_id: str = Field(min_length=1, description="Unipile seat (account id)")
    post_id_field: str = Field("post_id", description="custom_fields key holding the target post id")
    comment_template: str = Field(min_length=1, description="Comment body (supports {first_name} etc.)")


MANIFEST = NodeManifest(
    type="channel.linkedin_comment_post",
    category=NodeCategory.SINK,
    display_name="Comment on LinkedIn post",
    summary="Comment on a LinkedIn post from a seat (Unipile)",
    config_schema=LinkedInCommentPostConfig,
    output_handles=(
        NodeHandle("sent", "Comment posted"),
        NodeHandle("on_error", "Comment failed"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="message-square",
    primary_fields=("connection_name", "unipile_account_id", "comment_template"),
    advanced_fields=("post_id_field",),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInCommentPostConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    cf = ctx.lead.get("custom_fields") or {}
    post_id = cf.get(cfg.post_id_field) or ctx.config.get("post_id")
    return NodeResult(
        handle="sent",
        events=[
            {
                "event_type": "channel.linkedin_comment_post.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "unipile",
                    "connection_name": cfg.connection_name,
                    "unipile_account_id": cfg.unipile_account_id,
                    "post_id": post_id,
                    # The dispatcher/render layer resolves *_template into `body`.
                    "comment_template": cfg.comment_template,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "unipile"},
    )


register(MANIFEST, execute)
