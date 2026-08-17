"""Branch on whether the lead has replied within a window."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

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
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    # CONTRACT-006: evaluate against the contact's most recent inbound message.
    # The transition worker resolves ``last_inbound_at`` (ISO string) from
    # omni_messages and injects it into the lead context before firing this node
    # — the node has no DB handle of its own. Reply seen inside the window -> true.
    last_inbound_raw = ctx.lead.get("last_inbound_at")
    replied = False
    if last_inbound_raw:
        try:
            last_inbound = datetime.fromisoformat(last_inbound_raw)
            if last_inbound.tzinfo is None:
                last_inbound = last_inbound.replace(tzinfo=UTC)
            cutoff = datetime.now(UTC) - timedelta(days=cfg.window_days)
            replied = last_inbound >= cutoff
        except (TypeError, ValueError):
            replied = False
    return NodeResult(
        handle="true" if replied else "false",
        telemetry={
            "window_days": cfg.window_days,
            "channel": cfg.channel,
            "matched": replied,
            "correlation_id": correlation_id,
        },
    )


register(MANIFEST, execute)
