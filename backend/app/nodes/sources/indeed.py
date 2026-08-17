"""Indeed jobs source — Apify-driven discovery of hiring companies.

Runs the ``curious_coder~indeed-scraper`` Apify actor (one run per keyword),
polls until completion, fetches the dataset, dedupes by company, and emits a
``source.indeed.requested`` intent. The Rust muscle's INDEED handler runs the
actor + poll loop (a multi-step protocol, like ``source.linkedin_jobs``).

The result lands in the lead's ``custom_fields[companies_key]`` as a list —
exactly the shape ``flow.for_each`` iterates, one company per child lead — and
in the SAME row shape as source.naukri / source.linkedin_jobs, so the
downstream resolve/filter/people pipeline works unchanged.

Ported from omniagenticai/omni-outreach feature/dev-automation
(omni_outreach_v3/src/collectors/indeed.rs), re-homed as a v2 source node so
Indeed leads flow into the event log -> CRM/canvas/channels. Shares the Apify
connection with source.linkedin_jobs.
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


class IndeedSourceConfig(BaseModel):
    connection_name: str = Field(description="Apify connection (Settings -> Integrations)")
    keywords: list[str] = Field(min_length=1, description="Job keywords, one Apify run per keyword")
    location: str | None = Field(None, description="Indeed location filter, e.g. 'New York'")
    country: str = Field("us", description="Indeed actor country code, e.g. 'us', 'in', 'gb'")
    max_results: int = Field(
        50, ge=10, le=1000, description="Max job listings per keyword (Apify minimum 10)"
    )
    actor_id: str = Field(
        "curious_coder~indeed-scraper", description="Apify actor identifier (owner~slug)"
    )
    companies_key: str = Field(
        "companies",
        description="Key under custom_fields where the deduped company list lands",
    )
    min_results: int = Field(
        1, ge=0, description="Abort (handle=empty) if Apify returns fewer jobs than this"
    )


MANIFEST = NodeManifest(
    type="source.indeed",
    category=NodeCategory.SOURCE,
    summary="Pull hiring companies from Indeed.com job postings via Apify",
    config_schema=IndeedSourceConfig,
    output_handles=(
        NodeHandle("default", "Companies discovered; list lands in custom_fields[companies_key]"),
        NodeHandle("empty", "Apify returned fewer than min_results"),
        NodeHandle("on_error", "Actor run failed or timed out"),
    ),
    capabilities=("connection:apify",),
    side_effect=SideEffect.NETWORK,
    icon="briefcase",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = IndeedSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.indeed.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "connection_name": cfg.connection_name,
                "actor_id": cfg.actor_id,
                "keywords": cfg.keywords,
                "location": cfg.location,
                "country": cfg.country,
                "max_results": cfg.max_results,
                "min_results": cfg.min_results,
                "companies_key": cfg.companies_key,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(
        handle="default",
        events=events,
        telemetry={"correlation_id": correlation_id, "keywords": cfg.keywords},
    )


register(MANIFEST, execute)
