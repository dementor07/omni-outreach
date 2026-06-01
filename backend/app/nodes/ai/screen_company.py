"""Claude company screen — accept/reject one company against a free-form prompt.

Per-company gate that runs after the pure filters. Sends the company name +
sector + the operator's screening_prompt to Claude; the worker reads the
verdict (ACCEPT/REJECT) and walks the matching handle.

Asymmetry preserved from the original scraper (pipeline.py:148-165):
**fail-open** on Claude error -> ``accept`` handle. The reasoning is that
LLM flakiness shouldn't lose valid companies; the per-person screen later
catches the same companies anyway, with the opposite (fail-closed) policy.
"""

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


class ScreenCompanyConfig(BaseModel):
    connection_name: str = Field(description="Anthropic connection (Settings -> Integrations)")
    screening_prompt: str = Field(
        min_length=1, description="ICP definition fed to Claude as the screening rubric"
    )
    company_field: str = Field(
        "item",
        description="custom_fields key holding the company dict to screen "
        "(default 'item' — what flow.for_each writes per child)",
    )
    model: str = Field("claude-haiku-4-5-20251001", description="Anthropic model id")


MANIFEST = NodeManifest(
    type="ai.screen_company",
    category=NodeCategory.AI,
    summary="LLM verdict on whether a company matches the ICP prompt",
    config_schema=ScreenCompanyConfig,
    output_handles=(
        NodeHandle("accept", "Claude returned ACCEPT (or errored — fail-open)"),
        NodeHandle("reject", "Claude returned REJECT"),
    ),
    capabilities=("connection:anthropic",),
    side_effect=SideEffect.NETWORK,
    icon="check-circle",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ScreenCompanyConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    company = (ctx.lead.get("custom_fields") or {}).get(cfg.company_field) or {}
    events = [
        {
            "event_type": "ai.screen_company.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "model": cfg.model,
                "screening_prompt": cfg.screening_prompt,
                "company_name": company.get("company_name"),
                "sector": company.get("sector") or company.get("industry"),
                "on_error_handle": "accept",  # fail-open
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="accept", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
