"""Park the lead until an email is opened.

The transition worker will park the lead. When the tracking pixel fires, it emits an email.opened event. 
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

class EmailOpenedConfig(BaseModel):
    timeout_hours: int = Field(72, ge=1, le=720, description="Auto-resume on the timeout handle if not opened")

MANIFEST = NodeManifest(
    type="event.email_opened",
    category=NodeCategory.EVENT,
    summary="Pause the lead until an email is opened",
    config_schema=EmailOpenedConfig,
    output_handles=(
        NodeHandle("opened", "The lead opened the email"),
        NodeHandle("timeout", "The lead did not open the email within the timeout window"),
    ),
    side_effect=SideEffect.READ,
    icon="mail-open",
)

async def execute(ctx: NodeContext) -> NodeResult:
    cfg = EmailOpenedConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    
    return NodeResult(
        handle="opened",
        events=[
            {
                "event_type": "wait.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "reason": "email.opened",
                    "timeout_hours": cfg.timeout_hours,
                    "node_id": ctx.node_id,
                    "correlation_id": correlation_id,
                },
            }
        ],
        park=True,
        telemetry={"correlation_id": correlation_id, "parked": True, "reason": "email.opened"},
    )

register(MANIFEST, execute)
