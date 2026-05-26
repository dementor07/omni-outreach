"""AI research enrichment — find LinkedIn + role + company + recent news.

Search-grounded LLM call. Cheaper than ProxyCurl for lead-level research
when you only have a name + company; expensive but thorough vs. raw
single-shot LLM calls for the same task.
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


class AiEnrichConfig(BaseModel):
    provider: Literal["mindstudio", "gemini", "anthropic", "openai"] = Field(
        "mindstudio",
        description="MindStudio is the strongest at task-agent research; Gemini's grounding is the cheap option.",
    )
    fields: list[str] = Field(
        default_factory=lambda: ["linkedin_url", "current_role", "company_summary", "recent_news"],
        description="Which structured fields the agent must return",
    )


MANIFEST = NodeManifest(
    type="ai.enrich",
    category=NodeCategory.ENRICH,
    summary="Run a research agent that fills missing lead fields via web search + LLM reasoning",
    config_schema=AiEnrichConfig,
    output_handles=(
        NodeHandle("default", "Enrichment fields written to the contact"),
        NodeHandle("empty", "Agent could not find sufficient public info"),
        NodeHandle("on_error", "AI provider failed"),
    ),
    capabilities=("connection:mindstudio", "connection:gemini", "connection:anthropic", "connection:openai"),
    side_effect=SideEffect.NETWORK,
    icon="search",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = AiEnrichConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "ai.enrich.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "provider": cfg.provider,
                "fields": cfg.fields,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
