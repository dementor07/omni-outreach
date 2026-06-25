"""Clutch company discovery — headless scrape of a Clutch directory category.

Renders a Clutch agency directory page (e.g.
``clutch.co/agencies/lead-generation``) via the internal Camoufox service,
extracts each listed agency's name + website, and writes the deduped companies
to ``custom_fields[companies_key]`` for ``flow.for_each``. No API key — Camoufox
is internal infra (authed by a shared secret header).

Emits ``source.clutch.requested``; the Rust muscle's CLUTCH handler
(handlers/discovery.rs) calls Camoufox /scrape_directory and shapes the result.
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


class ClutchSourceConfig(BaseModel):
    directory_url: str = Field(
        "https://clutch.co/agencies/lead-generation",
        description="Clutch directory category URL to scrape",
    )
    titles: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_TITLES),
        description="Decision-maker titles propagated to each company for downstream people-discovery",
    )
    max_results: int = Field(25, ge=1, le=200, description="Cap on agencies returned per run")
    companies_key: str = Field(
        "companies",
        description="custom_fields key where the deduped company list lands for flow.for_each",
    )


MANIFEST = NodeManifest(
    type="source.clutch",
    category=NodeCategory.SOURCE,
    summary="Discover agencies by scraping a Clutch directory page (Camoufox, no API key)",
    config_schema=ClutchSourceConfig,
    output_handles=(
        NodeHandle("default", "Agencies discovered; list lands in custom_fields[companies_key]"),
        NodeHandle("empty", "Directory returned no agencies"),
        NodeHandle("on_error", "Scrape failed (captcha / service down)"),
    ),
    side_effect=SideEffect.NETWORK,
    icon="building",
    primary_fields=("directory_url",),
    advanced_fields=("titles", "max_results", "companies_key"),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ClutchSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.clutch.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "directory_url": cfg.directory_url,
                "titles": cfg.titles,
                "max_results": cfg.max_results,
                "companies_key": cfg.companies_key,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
