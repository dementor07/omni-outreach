"""Hold a lead until a business-hours / day-of-week window opens.

The orchestrator computes the next matching wall-clock time in the workflow's
timezone and registers a timer. This node just declares the window contract.
"""

from __future__ import annotations

from pydantic import BaseModel, Field, field_validator

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class WaitUntilConfig(BaseModel):
    earliest_hour: int = Field(9, ge=0, le=23, description="Earliest local hour to release the lead (0–23)")
    latest_hour: int = Field(17, ge=1, le=24, description="Latest local hour to release the lead (1–24)")
    days_of_week: list[int] = Field(
        default=[0, 1, 2, 3, 4],
        description="Allowed weekdays (0=Mon … 6=Sun). Default Mon–Fri.",
    )

    @field_validator("days_of_week")
    @classmethod
    def _check_days(cls, v: list[int]) -> list[int]:
        if not v or any(d < 0 or d > 6 for d in v):
            raise ValueError("days_of_week must contain values 0–6")
        return sorted(set(v))


MANIFEST = NodeManifest(
    type="flow.wait_until",
    category=NodeCategory.FLOW,
    summary="Hold the lead until the next business-hours window opens",
    config_schema=WaitUntilConfig,
    output_handles=(NodeHandle("default", "Emitted when the window opens"),),
    side_effect=SideEffect.READ,
    icon="clock",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = WaitUntilConfig(**ctx.config)
    if cfg.latest_hour <= cfg.earliest_hour:
        return NodeResult(handle="default", error="WAIT_UNTIL_INVALID_WINDOW")
    return NodeResult(
        handle="default",
        telemetry={
            "earliest_hour": cfg.earliest_hour,
            "latest_hour": cfg.latest_hour,
            "days_of_week": cfg.days_of_week,
        },
    )


register(MANIFEST, execute)
