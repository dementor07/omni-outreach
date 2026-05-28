"""Conversion goal — mark the lead as converted and stop the sequence.

When a lead reaches this node the orchestrator records the conversion against
the workflow's goal metric (used by Analytics) and removes the lead from any
pending timers/branches.
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


class GoalConfig(BaseModel):
    goal_name: str = Field("converted", min_length=1, max_length=80, description="Name of the conversion this goal records")
    value: float | None = Field(None, description="Optional monetary value attributed to the conversion")


MANIFEST = NodeManifest(
    type="flow.goal",
    category=NodeCategory.FLOW,
    summary="Mark the lead as converted and record a conversion goal",
    config_schema=GoalConfig,
    output_handles=(NodeHandle("default", "Goal recorded; lead exits the sequence"),),
    side_effect=SideEffect.MUTATE,
    icon="target",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = GoalConfig(**ctx.config)
    events = [
        {
            "event_type": "lead.goal_reached",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {"goal_name": cfg.goal_name, "value": cfg.value},
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"goal_name": cfg.goal_name})


register(MANIFEST, execute)
