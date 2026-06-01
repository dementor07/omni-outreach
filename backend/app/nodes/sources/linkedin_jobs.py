"""LinkedIn jobs source — Apify-driven discovery of hiring companies.

Runs the ``curious_coder~linkedin-jobs-scraper`` Apify actor with one search
URL per keyword, polls until completion, fetches the dataset, dedupes by
company, and emits a ``source.linkedin_jobs.requested`` intent event. The
generic Rust handler runs the actor + poll loop (it's a multi-step protocol:
POST run, poll status, GET dataset — not a single HTTP call, so it can't
be expressed as ``http_node``).

The result lands in the lead's ``custom_fields[companies_key]`` as a list,
which the downstream ``flow.for_each`` iterates one company at a time.

This is the *source* fan-out (1 query -> N companies). The interior fan-out
(1 company -> P people) is handled later via ``source.serper_people`` +
``flow.for_each``.

Ported from scraper/pipeline.py:108-125 (Apify run + extract_companies).
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


class LinkedInJobsSourceConfig(BaseModel):
    connection_name: str = Field(description="Apify connection (Settings -> Integrations)")
    keywords: list[str] = Field(min_length=1, description="Job keywords, one search URL built per keyword")
    location: str | None = Field(None, description="LinkedIn location filter, e.g. 'India'")
    date_posted: str = Field(
        "r86400",
        description="LinkedIn f_TPR filter: r86400=24h, r604800=week, r2592000=month",
    )
    max_results: int = Field(100, ge=1, le=1000, description="Max job listings to retrieve")
    actor_id: str = Field(
        "curious_coder~linkedin-jobs-scraper", description="Apify actor identifier (owner~slug)"
    )
    companies_key: str = Field(
        "companies",
        description="Key under custom_fields where the deduped company list lands",
    )
    min_results: int = Field(
        5,
        ge=0,
        description="Abort run if Apify returns fewer than this — likely actor failure",
    )


MANIFEST = NodeManifest(
    type="source.linkedin_jobs",
    category=NodeCategory.SOURCE,
    summary="Pull hiring companies from LinkedIn job postings via Apify",
    config_schema=LinkedInJobsSourceConfig,
    output_handles=(
        NodeHandle("default", "Companies discovered; list lands in custom_fields[companies_key]"),
        NodeHandle("empty", "Apify returned fewer than min_results — aborted"),
        NodeHandle("on_error", "Actor run failed or timed out"),
    ),
    capabilities=("connection:apify",),
    side_effect=SideEffect.NETWORK,
    icon="briefcase",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInJobsSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.linkedin_jobs.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "connection_name": cfg.connection_name,
                "actor_id": cfg.actor_id,
                "keywords": cfg.keywords,
                "location": cfg.location,
                "date_posted": cfg.date_posted,
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
