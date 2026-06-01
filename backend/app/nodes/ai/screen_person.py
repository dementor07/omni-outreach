"""Claude person screen — accept/reject one prospective contact.

Per-person gate that runs inside the for_each(people) body, after the Serper
search has emitted profile candidates. Sends the person's name + headline +
company + the operator's screening_prompt to Claude.

Asymmetry preserved from the original scraper (pipeline.py:208-226):
**fail-closed** on Claude error -> ``reject`` handle. The reasoning is that
the volume of candidate people is high and admitting an LLM-error person to
the CRM is more costly than dropping a legitimate one.
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


class ScreenPersonConfig(BaseModel):
    connection_name: str = Field(description="Anthropic connection (Settings -> Integrations)")
    screening_prompt: str = Field(
        min_length=1, description="ICP definition fed to Claude as the screening rubric"
    )
    person_field: str = Field(
        "item",
        description="custom_fields key holding the profile dict to screen "
        "(default 'item' — what flow.for_each writes per child)",
    )
    model: str = Field("claude-haiku-4-5-20251001", description="Anthropic model id")


MANIFEST = NodeManifest(
    type="ai.screen_person",
    category=NodeCategory.AI,
    summary="LLM verdict on whether a person matches the ICP prompt",
    config_schema=ScreenPersonConfig,
    output_handles=(
        NodeHandle("accept", "Claude returned ACCEPT"),
        NodeHandle("reject", "Claude returned REJECT (or errored — fail-closed)"),
    ),
    capabilities=("connection:anthropic",),
    side_effect=SideEffect.NETWORK,
    icon="user-check",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ScreenPersonConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    profile = (ctx.lead.get("custom_fields") or {}).get(cfg.person_field) or {}
    events = [
        {
            "event_type": "ai.screen_person.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "model": cfg.model,
                "screening_prompt": cfg.screening_prompt,
                "profile": {
                    "first_name": profile.get("first_name"),
                    "last_name": profile.get("last_name"),
                    "headline": profile.get("headline"),
                    "linkedin_url": profile.get("linkedin_url"),
                    "company_name": profile.get("company_name"),
                    "industry": profile.get("industry"),
                },
                "on_error_handle": "reject",  # fail-closed
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="accept", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
