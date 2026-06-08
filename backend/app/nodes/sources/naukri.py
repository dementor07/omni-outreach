"""Naukri.com jobs source — Camoufox-driven discovery of hiring companies.

Emits a ``source.naukri.requested`` intent. The Rust muscle's NAUKRI handler
calls the Camoufox microservice (anti-detect headless browser) to scrape
naukri.com job listings for one role keyword, dedupes by company, and writes the
company list to ``lead_mutations.custom_fields[companies_key]`` — exactly the
shape ``flow.for_each`` iterates, one company per child lead.

This is the source fan-out (1 keyword -> N companies). Downstream nodes resolve
each company (dedup/KG), filter, signal-score, discover people, and verify into
leads — the same interior pipeline as source.linkedin_jobs.

CAVEAT — the captured ``/jobapi/v3/search`` JSON carries NO ``employee_count``
and NO structured ``industry`` per company. So for Naukri-sourced companies the
KG ``filter_company`` employee cap and any industry/domain signal gating are
NO-OPS (they only bite for sources that supply those fields, e.g. LinkedIn jobs
+ enrichment). Naukri companies are gated by name blocklist + JD-keyword +
hiring-signal score only. To enforce the size cap on Naukri leads, enrich the
company (domain -> employee count) before ``crm.resolve_company``.

Ported from omniagenticai/omni-outreach feature/dev-automation
(omni_outreach_v3 NaukriCollector + Camoufox scraper), re-homed as a v2 source
node so leads flow into the event log -> CRM/canvas/channels instead of a
dead-end table.
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


class NaukriSourceConfig(BaseModel):
    keyword: str = Field(
        min_length=1,
        description="ONE role keyword per run for clean results, e.g. 'SDR' or 'Account Executive'",
    )
    location: str | None = Field(None, description="Optional Naukri location filter, e.g. 'India'")
    max_pages: int = Field(
        5, ge=1, le=50, description="Pages to scrape (~20 jobs/page). 5 pages ~= 100 jobs"
    )
    companies_key: str = Field(
        "companies",
        description="custom_fields key where the deduped company list lands for flow.for_each",
    )
    min_results: int = Field(
        1, ge=0, description="Abort (handle=empty) if Camoufox returns fewer jobs than this"
    )


MANIFEST = NodeManifest(
    type="source.naukri",
    category=NodeCategory.SOURCE,
    summary="Pull hiring companies from Naukri.com job postings (Camoufox anti-detect scraper)",
    config_schema=NaukriSourceConfig,
    output_handles=(
        NodeHandle("default", "Companies discovered; list lands in custom_fields[companies_key]"),
        NodeHandle("empty", "Camoufox returned fewer than min_results"),
        NodeHandle("on_error", "Scrape failed (captcha / service down)"),
    ),
    # No external connection/credential — the Camoufox service is internal infra,
    # not a per-workspace API key. Hence no capabilities=("connection:...",).
    side_effect=SideEffect.NETWORK,
    icon="search",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = NaukriSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.naukri.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "keyword": cfg.keyword,
                "location": cfg.location,
                "max_pages": cfg.max_pages,
                "min_results": cfg.min_results,
                "companies_key": cfg.companies_key,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(
        handle="default",
        events=events,
        telemetry={"correlation_id": correlation_id, "keyword": cfg.keyword},
    )


register(MANIFEST, execute)
