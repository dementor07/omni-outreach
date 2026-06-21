"""LinkedIn channel node — invite / DM / profile-view / InMail via Unipile.

Operators pick one ``mode`` on the node config; the Rust muscle's Unipile
handlers route by command channel. This node only validates config and
queues the action; the muscle owns the network call.
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


class LinkedInChannelConfig(BaseModel):
    connection_name: str | None = Field(None, description="Unipile connection name (Settings → Integrations)")
    sending_account_id: str | None = None
    account_pool: Literal["campaign", "round_robin", "single"] | None = None
    mode: Literal["invite", "dm", "profile_view", "inmail"] = Field(description="Which LinkedIn action to perform")
    message_template: str | None = Field(None, description="Required for invite/dm/inmail; supports {{contact.first_name}}-style variables")
    subject_template: str | None = Field(None, description="Required only for inmail")


MANIFEST = NodeManifest(
    type="channel.linkedin",
    category=NodeCategory.CHANNEL,
    summary="LinkedIn invite, DM, profile-view, or InMail via Unipile",
    config_schema=LinkedInChannelConfig,
    output_handles=(
        NodeHandle("sent", "Action accepted by Unipile"),
        NodeHandle("on_error", "Permanent failure (account limit, blocked profile, …)"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="linkedin",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInChannelConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": f"channel.linkedin.{cfg.mode}.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "mode": cfg.mode,
                "message_template": cfg.message_template,
                "subject_template": cfg.subject_template,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="sent", events=events, telemetry={"correlation_id": correlation_id, "mode": cfg.mode})


register(MANIFEST, execute)
