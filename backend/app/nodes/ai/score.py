"""AI ICP scorer — score a lead 0-100 against an ICP definition."""

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


class AiScoreConfig(BaseModel):
    provider: Literal["anthropic", "openai", "gemini", "mindstudio"] = "anthropic"
    icp_description: str = Field(
        min_length=10,
        max_length=4000,
        description="What your ideal customer looks like — title, industry, size, geo, pain, …",
    )
    target_variable: str = Field("icp_score", description="Where to store the 0-100 score on the lead context")


MANIFEST = NodeManifest(
    type="ai.score",
    category=NodeCategory.AI,
    summary="Score the current lead 0-100 against an ICP rubric",
    config_schema=AiScoreConfig,
    output_handles=(
        NodeHandle("default", "Score stored on the lead context"),
        NodeHandle("on_error", "AI provider failed"),
    ),
    capabilities=("connection:anthropic", "connection:openai", "connection:gemini", "connection:mindstudio"),
    side_effect=SideEffect.NETWORK,
    icon="gauge",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = AiScoreConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "ai.score.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "provider": cfg.provider,
                "icp_description": cfg.icp_description,
                "target_variable": cfg.target_variable,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
