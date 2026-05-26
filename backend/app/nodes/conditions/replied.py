"""Branch on whether the lead has replied within a window."""

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


class RepliedConditionConfig(BaseModel):
    window_days: int = Field(7, ge=1, le=365, description="Only count replies in the last N days")
    channel: str | None = Field(None, description="Optional — filter to one channel (email, linkedin, …)")


MANIFEST = NodeManifest(
    type="condition.replied",
    category=NodeCategory.CONDITION,
    summary="Has the lead replied to any outbound message in the last N days?",
    config_schema=RepliedConditionConfig,
    output_handles=(
        NodeHandle("true", "Reply seen inside the window"),
        NodeHandle("false", "No reply in the window"),
    ),
    side_effect=SideEffect.READ,
    icon="reply",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = RepliedConditionConfig(**ctx.config)
    # The actual check happens in the orchestrator against omni_messages —
    # this node just declares the decision shape. The orchestrator picks
    # `true` or `false` based on the message store.
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="false",
        telemetry={"window_days": cfg.window_days, "channel": cfg.channel, "correlation_id": correlation_id},
    )


register(MANIFEST, execute)
