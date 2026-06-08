"""Wait a fixed duration before continuing.

The transition worker computes the delay (amount × unit) from this node's
config and emits a *delayed* synthetic result; the Flink orchestrator's
processing-time timer holds the lead (status='waiting') and fires the
transition when it elapses. execute() only validates + reports the duration.
"""

from __future__ import annotations

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

_UNIT_SECONDS = {"minutes": 60, "hours": 3600, "days": 86400}


class DelayConfig(BaseModel):
    amount: int = Field(ge=1, description="How many units to wait")
    unit: Literal["minutes", "hours", "days"] = "hours"


MANIFEST = NodeManifest(
    type="flow.delay",
    category=NodeCategory.FLOW,
    summary="Wait a fixed amount of time before advancing the lead",
    config_schema=DelayConfig,
    output_handles=(NodeHandle("default", "Emitted once the timer fires"),),
    side_effect=SideEffect.READ,
    icon="clock",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = DelayConfig(**ctx.config)
    seconds = cfg.amount * _UNIT_SECONDS[cfg.unit]
    return NodeResult(
        handle="default",
        telemetry={"delay_seconds": seconds, "amount": cfg.amount, "unit": cfg.unit},
    )


register(MANIFEST, execute)
