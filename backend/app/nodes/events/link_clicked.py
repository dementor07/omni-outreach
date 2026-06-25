"""Park the lead until a link is clicked.

The transition worker will park the lead. When the tracking pixel fires, it emits an email.clicked event. 
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

class LinkClickedConfig(BaseModel):
    timeout_hours: int = Field(72, ge=1, le=720, description="Auto-resume on the timeout handle if no link is clicked")

MANIFEST = NodeManifest(
    type="event.link_clicked",
    category=NodeCategory.EVENT,
    summary="Pause the lead until a link is clicked",
    config_schema=LinkClickedConfig,
    output_handles=(
        NodeHandle("clicked", "The lead clicked a link"),
        NodeHandle("timeout", "The lead did not click a link within the timeout window"),
    ),
    side_effect=SideEffect.READ,
    icon="mouse-pointer",
)

async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkClickedConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    
    return NodeResult(
        handle="clicked",
        events=[
            {
                "event_type": "wait.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "reason": "email.clicked",
                    "timeout_hours": cfg.timeout_hours,
                    "node_id": ctx.node_id,
                    "correlation_id": correlation_id,
                },
            }
        ],
        park=True,
        telemetry={"correlation_id": correlation_id, "parked": True, "reason": "email.clicked"},
    )

register(MANIFEST, execute)
