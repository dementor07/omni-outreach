"""Explicit terminal — stop the sequence for this lead without a conversion.

Useful for unsubscribe / disqualified / dead-end branches so leads aren't left
dangling on a node with no outgoing edge.
"""

from __future__ import annotations

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


class EndConfig(BaseModel):
    reason: str = Field("completed", min_length=1, max_length=80, description="Why the sequence ended (completed, unsubscribed, disqualified, …)")


MANIFEST = NodeManifest(
    type="flow.end",
    category=NodeCategory.FLOW,
    summary="Stop the sequence for this lead (terminal node)",
    config_schema=EndConfig,
    output_handles=(),
    side_effect=SideEffect.MUTATE,
    icon="octagon-x",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = EndConfig(**ctx.config)
    events = [
        {
            "event_type": "lead.sequence_ended",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {"reason": cfg.reason},
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"reason": cfg.reason})


register(MANIFEST, execute)
