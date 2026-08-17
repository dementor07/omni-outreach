"""channel.invite_cancel — cancel a pending LinkedIn invitation (Unipile).

A per-lead ACTION (real side effect) — gated like a message in a campaign.
Routes to ChannelType.InviteCancel. The invitation id comes from custom_fields
(recorded when the invite was sent) or config.
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


class InviteCancelConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection")
    unipile_account_id: str = Field(min_length=1, description="Unipile seat (account id)")
    invitation_id_field: str = Field("invitation_id", description="custom_fields key holding the invitation id")


MANIFEST = NodeManifest(
    type="channel.invite_cancel",
    category=NodeCategory.SINK,
    display_name="Cancel LinkedIn invite",
    summary="Cancel a pending connection invitation from a seat (Unipile)",
    config_schema=InviteCancelConfig,
    output_handles=(
        NodeHandle("sent", "Invitation cancelled"),
        NodeHandle("on_error", "Cancellation failed"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="user-x",
    primary_fields=("connection_name", "unipile_account_id"),
    advanced_fields=("invitation_id_field",),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = InviteCancelConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    cf = ctx.lead.get("custom_fields") or {}
    invitation_id = cf.get(cfg.invitation_id_field) or ctx.config.get("invitation_id")
    return NodeResult(
        handle="sent",
        events=[
            {
                "event_type": "channel.invite_cancel.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "unipile",
                    "connection_name": cfg.connection_name,
                    "unipile_account_id": cfg.unipile_account_id,
                    "invitation_id": invitation_id,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "unipile"},
    )


register(MANIFEST, execute)
