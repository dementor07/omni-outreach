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
    jitter_pct: int = Field(
        0,
        ge=0,
        le=100,
        description=(
            "Randomize the wait by ±this percent per lead (anti-detection). 0 = exact. "
            "e.g. 20 on a 3-day wait = each lead waits ~2.4–3.6 days, deterministic per lead "
            "so redelivery doesn't drift the timer."
        ),
    )


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
    # The actual (possibly jittered) hold is computed by the transition worker,
    # which has the lead id for a deterministic per-lead offset. execute() only
    # reports the configured base for telemetry/validation.
    return NodeResult(
        handle="default",
        telemetry={"delay_seconds": seconds, "amount": cfg.amount, "unit": cfg.unit, "jitter_pct": cfg.jitter_pct},
    )


register(MANIFEST, execute)
