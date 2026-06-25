"""Park the lead until a LinkedIn connection invite is accepted.

The transition worker will park the lead. When the Unipile webhook fires, it emits an invite.accepted event. 
The event router matches this event to the parked lead and resumes it.
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

class InviteAcceptedConfig(BaseModel):
    timeout_hours: int = Field(168, ge=1, le=720, description="Auto-resume on the timeout handle if the invite is not accepted (default 1 week)")

MANIFEST = NodeManifest(
    type="event.invite_accepted",
    category=NodeCategory.EVENT,
    summary="Pause the lead until a LinkedIn connection invite is accepted",
    config_schema=InviteAcceptedConfig,
    output_handles=(
        NodeHandle("accepted", "The lead accepted the connection invite"),
        NodeHandle("timeout", "The lead did not accept within the timeout window"),
    ),
    side_effect=SideEffect.READ,
    icon="user-check",
)

async def execute(ctx: NodeContext) -> NodeResult:
    cfg = InviteAcceptedConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    
    return NodeResult(
        handle="accepted",
        events=[
            {
                "event_type": "wait.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "reason": "linkedin.invite_accepted",
                    "timeout_hours": cfg.timeout_hours,
                    "node_id": ctx.node_id,
                    "correlation_id": correlation_id,
                },
            }
        ],
        park=True,
        telemetry={"correlation_id": correlation_id, "parked": True, "reason": "linkedin.invite_accepted"},
    )

register(MANIFEST, execute)
