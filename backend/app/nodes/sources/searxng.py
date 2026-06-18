"""SearXNG company discovery — free, self-hosted, keyless web search.

Runs a Google-style dork against your self-hosted SearXNG instance (e.g.
``site:clutch.co lead generation agency``) and writes the deduped companies to
``custom_fields[companies_key]`` for ``flow.for_each``. No API key — SearXNG is
internal infra, the economic equalizer. For the paid Google API, use
``source.serper_search`` instead; for an agency directory, ``source.clutch``.

Emits ``source.searxng.requested``; the Rust muscle's SEARXNG handler
(handlers/discovery.rs) runs the search and shapes the result.
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

_DEFAULT_TITLES = ["Founder", "CEO", "Co-Founder", "Managing Director", "Growth Head"]


class SearxngSourceConfig(BaseModel):
    query: str = Field(
        min_length=1,
        description="Search dork, e.g. 'site:clutch.co lead generation agency'",
    )
    titles: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_TITLES),
        description="Decision-maker titles propagated to each company for downstream people-discovery",
    )
    max_results: int = Field(25, ge=1, le=200, description="Cap on companies returned per run")
    companies_key: str = Field(
        "companies",
        description="custom_fields key where the deduped company list lands for flow.for_each",
    )
    searxng_url: str | None = Field(None, description="Override SearXNG base URL (else SEARXNG_URL env)")


MANIFEST = NodeManifest(
    type="source.searxng",
    category=NodeCategory.SOURCE,
    summary="Discover companies via free self-hosted SearXNG web search (no API key)",
    config_schema=SearxngSourceConfig,
    output_handles=(
        NodeHandle("default", "Companies discovered; list lands in custom_fields[companies_key]"),
        NodeHandle("empty", "No companies matched"),
        NodeHandle("on_error", "Search failed"),
    ),
    side_effect=SideEffect.NETWORK,
    icon="search",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = SearxngSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.searxng.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "query": cfg.query,
                "titles": cfg.titles,
                "max_results": cfg.max_results,
                "companies_key": cfg.companies_key,
                "searxng_url": cfg.searxng_url,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
