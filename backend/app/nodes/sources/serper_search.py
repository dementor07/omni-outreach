"""Serper company discovery — paid Google Search API (google.serper.dev).

Runs a Google-style dork via Serper (e.g. ``site:clutch.co lead generation
agency``) and writes the deduped companies to ``custom_fields[companies_key]``
for ``flow.for_each``. Needs a Serper connection (api_key). For the free,
keyless equivalent use ``source.searxng``.

Emits ``source.serper_search.requested``; the Rust muscle's SERPER_SEARCH
handler (handlers/discovery.rs) runs the search and shapes the result.
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


class SerperSearchSourceConfig(BaseModel):
    connection_name: str = Field(description="Serper connection (Settings → Integrations)")
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


MANIFEST = NodeManifest(
    type="source.serper_search",
    category=NodeCategory.SOURCE,
    summary="Discover companies via the paid Serper Google Search API (needs api_key)",
    config_schema=SerperSearchSourceConfig,
    output_handles=(
        NodeHandle("default", "Companies discovered; list lands in custom_fields[companies_key]"),
        NodeHandle("empty", "No companies matched"),
        NodeHandle("on_error", "Search failed"),
    ),
    capabilities=("connection:serper",),
    side_effect=SideEffect.NETWORK,
    icon="search",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = SerperSearchSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.serper_search.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "query": cfg.query,
                "titles": cfg.titles,
                "max_results": cfg.max_results,
                "companies_key": cfg.companies_key,
                "connection_name": cfg.connection_name,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
