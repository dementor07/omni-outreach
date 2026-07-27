"""Free LinkedIn jobs source — guest-API drop-in for ``source.linkedin_jobs``.

Same fan-out contract as the Apify-driven ``source.linkedin_jobs`` (1 query -> N
hiring companies landing in ``custom_fields[companies_key]`` for the downstream
``flow.for_each`` to iterate), but the fetch costs **nothing**: the Rust
``linkedin_jobs_guest`` handler scrapes LinkedIn's public *jobs-guest* endpoint
plus each company's public page for ``numberOfEmployees`` — no Apify credits, no
API key, no connection. The emitted company rows carry ``employee_count`` in the
exact shape ``apify::extract_companies`` produces, so the proven size-gate ->
resolve_company -> serper_people -> screen_person -> create_contact graph runs
unchanged.

Use this instead of ``source.linkedin_jobs`` whenever Apify credits are out or
the volume is small enough for LinkedIn's guest rate limits (fine for the
<100-employee targeted campaigns we run).
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


class LinkedInJobsGuestSourceConfig(BaseModel):
    keywords: list[str] = Field(
        min_length=1, description="Job keywords, one guest search per keyword"
    )
    location: str | None = Field(None, description="LinkedIn location filter, e.g. 'India'")
    date_posted: str = Field(
        "r604800",
        description="LinkedIn f_TPR filter: r86400=24h, r604800=week, r2592000=month",
    )
    max_results: int = Field(
        100, ge=1, le=400, description="Max job cards to collect across pagination"
    )
    companies_key: str = Field(
        "companies",
        description="Key under custom_fields where the deduped company list lands",
    )
    min_results: int = Field(
        5,
        ge=0,
        description="Abort run (handle=empty) if the guest API returns fewer cards — likely a block",
    )


MANIFEST = NodeManifest(
    type="source.linkedin_jobs_guest",
    category=NodeCategory.SOURCE,
    summary="Pull hiring companies from LinkedIn job postings — free guest API, no Apify",
    config_schema=LinkedInJobsGuestSourceConfig,
    output_handles=(
        NodeHandle("default", "Companies discovered; list lands in custom_fields[companies_key]"),
        NodeHandle("empty", "Guest API returned fewer than min_results — aborted"),
        NodeHandle("on_error", "Guest fetch failed (blocked / network)"),
    ),
    side_effect=SideEffect.NETWORK,
    icon="briefcase",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInJobsGuestSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.linkedin_jobs_guest.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
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
