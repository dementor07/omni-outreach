"""Branch on the lead's LinkedIn network distance (1st, 2nd, 3rd+)."""
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

class LinkedinDistanceConfig(BaseModel):
    fallback_handle: str = Field("out_of_network", description="Which path to take if the distance is unknown")

MANIFEST = NodeManifest(
    type="condition.linkedin_distance",
    category=NodeCategory.CONDITION,
    summary="Branch based on the lead's LinkedIn network distance",
    config_schema=LinkedinDistanceConfig,
    output_handles=(
        NodeHandle("1st", "You are already connected (1st degree)"),
        NodeHandle("2nd", "You share mutual connections (2nd degree)"),
        NodeHandle("out_of_network", "3rd degree or out of network"),
    ),
    side_effect=SideEffect.READ,
    icon="users",
)

async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedinDistanceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    
    cf = ctx.lead.get("custom_fields") or {}
    distance = str(cf.get("linkedin_distance") or cfg.fallback_handle).lower()
    
    if "1st" in distance or distance == "1":
        handle = "1st"
    elif "2nd" in distance or distance == "2":
        handle = "2nd"
    else:
        handle = "out_of_network"
        
    return NodeResult(
        handle=handle,
        telemetry={
            "distance": distance,
            "correlation_id": correlation_id,
        },
    )

register(MANIFEST, execute)
