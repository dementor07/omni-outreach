"""AI reply classifier — categorise an inbound message into intent buckets.

Used inside the reply-handling flow: an incoming message triggers this
node, the AI provider returns ``{category, confidence}``, downstream
condition nodes branch on it.
"""

from __future__ import annotations

import uuid
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


class AiClassifyConfig(BaseModel):
    provider: Literal["anthropic", "openai", "gemini", "mindstudio"] = "anthropic"
    categories: list[str] = Field(
        default_factory=lambda: ["positive", "objection", "out_of_office", "unsubscribe", "neutral"],
        description="Mutually-exclusive bucket names the AI must choose from",
    )
    target_variable: str = Field("reply_category", description="Where to store the chosen category on the lead context")


MANIFEST = NodeManifest(
    type="ai.classify",
    category=NodeCategory.AI,
    summary="Classify the lead's latest inbound message into one of N categories",
    config_schema=AiClassifyConfig,
    output_handles=(
        NodeHandle("default", "Classification stored on the lead context"),
        NodeHandle("on_error", "AI provider failed"),
    ),
    capabilities=("connection:anthropic", "connection:openai", "connection:gemini", "connection:mindstudio"),
    side_effect=SideEffect.NETWORK,
    icon="tags",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = AiClassifyConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "ai.classify.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "provider": cfg.provider,
                "categories": cfg.categories,
                "target_variable": cfg.target_variable,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
