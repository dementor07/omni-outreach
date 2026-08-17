"""SearXNG people discovery — free, keyless LinkedIn profile search.

Searches for LinkedIn profiles matching decision-maker titles at one company
via your self-hosted SearXNG instance, and writes the deduped list under
``custom_fields[people_key]`` for the downstream ``flow.for_each``. No API key —
the free equivalent of ``source.serper_people``.

Runs the same 2-pattern-per-role dedup loop as the Serper variant; only the
search backend differs (handlers/serper_people.rs, provider='searxng').
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


class SearxngPeopleSourceConfig(BaseModel):
    company_field: str = Field(
        "item",
        description="custom_fields key holding the company dict whose name we search for "
        "(default 'item' — what flow.for_each writes per child)",
    )
    titles: list[str] = Field(
        default_factory=lambda: ["CEO", "Founder", "Co-Founder", "CMO"],
        description="Decision-maker titles to search at the company",
    )
    max_per_company: int = Field(5, ge=1, le=50, description="Cap profiles returned per company")
    people_key: str = Field(
        "people",
        description="custom_fields key where the deduped profile list lands",
    )

    company_name_field: str | None = Field(
        None,
        description="custom_fields key holding the company name string to search for "
    )
    searxng_url: str | None = Field(None, description="Override SearXNG base URL (else SEARXNG_URL env)")


MANIFEST = NodeManifest(
    type="source.searxng_people",
    category=NodeCategory.SOURCE,
    summary="Find LinkedIn profiles at a company via free self-hosted SearXNG (no API key)",
    config_schema=SearxngPeopleSourceConfig,
    output_handles=(
        NodeHandle("default", "1+ profiles found; list lands in custom_fields[people_key]"),
        NodeHandle("empty", "No profiles matched"),
        NodeHandle("on_error", "Search call failed"),
    ),
    side_effect=SideEffect.NETWORK,
    icon="users",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = SearxngPeopleSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    company = (ctx.lead.get("custom_fields") or {}).get(cfg.company_field) or {}
    events = [
        {
            "event_type": "source.searxng_people.requested",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "company_field": cfg.company_field,
                "company_name_field": cfg.company_name_field,
                "provider": "searxng",
                "searxng_url": cfg.searxng_url or "",
                "company_name": company.get("company_name"),
                "industry": company.get("sector") or company.get("industry"),
                "titles": cfg.titles,
                "max_per_company": cfg.max_per_company,
                "people_key": cfg.people_key,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id, "provider": "searxng"})


register(MANIFEST, execute)
