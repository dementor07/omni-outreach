"""Voice channel node — Retell AI agent call via the Rust muscle's handle_voice."""

from __future__ import annotations

import uuid
from typing import Any, Literal

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


class VoiceChannelConfig(BaseModel):
    connection_name: str | None = Field(None, description="Retell connection name (Settings → Integrations)")
    sending_account_id: str | None = None
    account_pool: Literal["campaign", "round_robin", "single"] | None = None
    retell_agent_id: str = Field(min_length=1, description="The Retell agent that will run the call")
    conversation_flow_id: str | None = Field(None, description="Optional — for Nested Flow agents")
    from_number: str | None = Field(None, description="Override the connection's default outbound number")
    dynamic_variables: dict[str, Any] = Field(default_factory=dict, description="Per-call variables injected into the agent prompt")


MANIFEST = NodeManifest(
    type="channel.voice",
    category=NodeCategory.CHANNEL,
    summary="Place an AI voice call to the contact via Retell",
    config_schema=VoiceChannelConfig,
    output_handles=(
        NodeHandle("placed", "Retell accepted the create-call request"),
        NodeHandle("on_error", "Permanent failure (invalid phone, no credit, agent missing)"),
    ),
    capabilities=("connection:retell",),
    side_effect=SideEffect.NETWORK,
    icon="phone",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = VoiceChannelConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "channel.voice.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "retell_agent_id": cfg.retell_agent_id,
                "conversation_flow_id": cfg.conversation_flow_id,
                "from_number": cfg.from_number,
                "dynamic_variables": cfg.dynamic_variables,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="placed", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
