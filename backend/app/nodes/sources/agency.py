"""Agency / company discovery source — "Auto-Pilot Target Mining".

Finds companies matching an ICP and writes the deduped company list to
``lead_mutations.custom_fields[companies_key]`` — the exact shape
``flow.for_each`` iterates, one company per child lead. Downstream the same
interior pipeline as ``source.naukri`` resolves each company, discovers its
decision-makers (``source.serper_people``), verifies, screens, and creates a
contact.

This is the node that lets the tool find its own ICP (e.g. B2B lead-gen
agencies) and run the "Inception Loop" — outbound that sells the outbound tool.

Three providers (selected by ``provider``), all behind one Rust handler:
  - ``search``  Serper (paid) or SearXNG (free) Google dorks against agency
                directories, e.g. ``site:clutch.co lead generation agency``.
  - ``apollo``  Apollo organization-search API. Key optional — with no Apollo
                connection the node returns the ``empty`` handle so it ships
                before a key exists.
  - ``clutch``  Camoufox headless scrape of a Clutch directory category page.

Emits a ``source.agency.requested`` intent; the Rust AGENCY handler does the
work (see backend-rust/src/handlers/agency.rs).
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

# Sensible default ICP titles for B2B agencies — the decision-makers
# serper_people should look for once each agency is resolved.
_DEFAULT_TITLES = ["Founder", "CEO", "Co-Founder", "Managing Director", "Growth Head"]


class AgencySourceConfig(BaseModel):
    provider: Literal["search", "apollo", "clutch"] = Field(
        "search",
        description="search = Serper/SearXNG directory dorks; apollo = Apollo org API; clutch = Camoufox directory scrape",
    )
    query: str = Field(
        "site:clutch.co lead generation agency",
        description="Directory dork (search) or Apollo keyword (apollo). Ignored for clutch.",
    )
    directory_url: str | None = Field(
        None,
        description="Clutch category URL (clutch provider), e.g. https://clutch.co/agencies/lead-generation",
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
    search_provider: Literal["serper", "searxng"] = Field(
        "serper", description="search provider sub-toggle: serper (paid, needs key) | searxng (free)"
    )
    connection_name: str | None = Field(
        None, description="Serper or Apollo connection (Settings → Integrations). Not needed for searxng/clutch."
    )
    searxng_url: str | None = Field(None, description="Override SearXNG base URL (search_provider=searxng)")


MANIFEST = NodeManifest(
    type="source.agency",
    category=NodeCategory.SOURCE,
    summary="Discover companies/agencies matching an ICP (search dorks / Apollo / Clutch scrape) — Auto-Pilot Target Mining",
    config_schema=AgencySourceConfig,
    output_handles=(
        NodeHandle("default", "Companies discovered; list lands in custom_fields[companies_key]"),
        NodeHandle("empty", "No companies matched (or Apollo has no credential yet)"),
        NodeHandle("on_error", "Provider call failed"),
    ),
    # Serper/Apollo need a connection; searxng/clutch don't. Declared optional via
    # the connection_name config field rather than a hard capability so the node
    # can run keyless (searxng/clutch) too.
    capabilities=("connection:serper",),
    side_effect=SideEffect.NETWORK,
    icon="building",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = AgencySourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.agency.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "provider": cfg.provider,
                "query": cfg.query,
                "directory_url": cfg.directory_url,
                "titles": cfg.titles,
                "max_results": cfg.max_results,
                "companies_key": cfg.companies_key,
                "search_provider": cfg.search_provider,
                "searxng_url": cfg.searxng_url,
                "connection_name": cfg.connection_name,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(
        handle="default",
        events=events,
        telemetry={"correlation_id": correlation_id, "provider": cfg.provider},
    )


register(MANIFEST, execute)
