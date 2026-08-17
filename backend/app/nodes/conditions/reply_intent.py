"""Branch on the intent of the lead's most recent reply."""
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


class ReplyIntentConfig(BaseModel):
    fallback_handle: str = Field("unknown", description="Which path to take if the intent is not classified")

MANIFEST = NodeManifest(
    type="condition.reply_intent",
    category=NodeCategory.CONDITION,
    summary="Branch based on the classified intent of the last reply",
    config_schema=ReplyIntentConfig,
    output_handles=(
        NodeHandle("positive", "The reply was positive / interested"),
        NodeHandle("negative", "The reply was negative / opt-out"),
        NodeHandle("referral", "The reply referred you to someone else"),
        NodeHandle("later", "The reply asked to follow up later"),
        NodeHandle("unknown", "Intent was not classified or neutral"),
    ),
    side_effect=SideEffect.READ,
    icon="message-circle",
)

async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ReplyIntentConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())

    intent = str(ctx.lead.get("last_inbound_intent") or cfg.fallback_handle).lower()

    valid_handles = {"positive", "negative", "referral", "later", "unknown"}
    handle = intent if intent in valid_handles else cfg.fallback_handle

    return NodeResult(
        handle=handle,
        telemetry={
            "intent": intent,
            "correlation_id": correlation_id,
        },
    )

register(MANIFEST, execute)
