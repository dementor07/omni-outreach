"""channel.linkedin_endorse — endorse a member's skill (Unipile).

A per-lead social ACTION (real side effect) — gated like a message in a campaign.
Routes to ChannelType.LinkedinEndorse. The member is resolved from the lead's
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


class LinkedInEndorseConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection")
    unipile_account_id: str = Field(min_length=1, description="Unipile seat (account id)")
    skill: str | None = Field(None, description="Skill to endorse (optional; defaults to a top skill)")


MANIFEST = NodeManifest(
    type="channel.linkedin_endorse",
    category=NodeCategory.SINK,
    display_name="Endorse LinkedIn skill",
    summary="Endorse a member's skill from a seat (Unipile)",
    config_schema=LinkedInEndorseConfig,
    output_handles=(
        NodeHandle("sent", "Endorsement posted"),
        NodeHandle("on_error", "Endorsement failed"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="award",
    primary_fields=("connection_name", "unipile_account_id"),
    advanced_fields=("skill",),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInEndorseConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    cf = ctx.lead.get("custom_fields") or {}
    payload = {
        "provider": "unipile",
        "connection_name": cfg.connection_name,
        "unipile_account_id": cfg.unipile_account_id,
        "provider_id": cf.get("provider_id"),
        "correlation_id": correlation_id,
    }
    if cfg.skill:
        payload["skill"] = cfg.skill
    return NodeResult(
        handle="sent",
        events=[
            {
                "event_type": "channel.linkedin_endorse.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": payload,
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "unipile"},
    )


register(MANIFEST, execute)
