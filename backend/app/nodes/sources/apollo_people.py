"""Apollo native people search (APOLLO-DATA, native lead-gen).

Fan-out source: runs Apollo's ``POST /api/v1/mixed_people/api_search`` and writes
the deduped people list under ``custom_fields[people_key]`` for the downstream
``flow.for_each(people)`` to iterate — the same shape as ``source.serper_people``
/ ``source.linkedin_search``. This is native Apollo people lead-gen (no scraping),
the big new discovery capability. Needs an Apollo connection (api_key).

Emits ``source.apollo_people.requested``; the Rust muscle's ApolloPeople handler
(handlers/apollo_data.rs) POSTs the search and normalises each person.
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


class ApolloPeopleConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Apollo connection (Settings → Integrations)")
    person_titles: list[str] = Field(
        default_factory=list,
        description="Job titles to match, e.g. ['Head of Growth', 'VP Sales']",
    )
    person_seniorities: list[str] = Field(
        default_factory=list,
        description="Apollo seniority levels, e.g. ['founder', 'c_suite', 'director']",
    )
    organization_num_employees_ranges: list[str] = Field(
        default_factory=list,
        description="Company-size buckets as Apollo ranges, e.g. ['1,10', '11,50', '51,200']",
    )
    person_locations: list[str] = Field(
        default_factory=list,
        description="Person locations, e.g. ['United States', 'London']",
    )
    organization_locations: list[str] = Field(
        default_factory=list,
        description="Company HQ locations",
    )
    q_keywords: str | None = Field(
        None,
        max_length=255,
        description="Free-text keyword filter across the person/company",
    )
    page: int = Field(1, ge=1, le=500, description="Result page (Apollo paginates)")
    per_page: int = Field(25, ge=1, le=100, description="People per page (Apollo caps at 100)")
    people_key: str = Field(
        "people",
        min_length=1,
        description="custom_fields key where the deduped people list lands for flow.for_each",
    )


MANIFEST = NodeManifest(
    type="source.apollo_people",
    category=NodeCategory.SOURCE,
    display_name="Apollo people search",
    summary="Find people via Apollo's native people search — writes custom_fields[people_key]",
    config_schema=ApolloPeopleConfig,
    output_handles=(
        NodeHandle("default", "1+ people found; list lands in custom_fields[people_key]"),
        NodeHandle("empty", "No people matched"),

    ),
    capabilities=("connection:apollo",),
    side_effect=SideEffect.NETWORK,
    icon="users",
    primary_fields=("connection_name", "person_titles", "organization_num_employees_ranges"),
    advanced_fields=(
        "person_seniorities", "person_locations", "organization_locations",
        "q_keywords", "page", "per_page", "people_key",
    ),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ApolloPeopleConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    payload = {
        "provider": "apollo",
        "connection_name": cfg.connection_name,
        "person_titles": cfg.person_titles,
        "person_seniorities": cfg.person_seniorities,
        "organization_num_employees_ranges": cfg.organization_num_employees_ranges,
        "person_locations": cfg.person_locations,
        "organization_locations": cfg.organization_locations,
        "page": cfg.page,
        "per_page": cfg.per_page,
        "people_key": cfg.people_key,
        "correlation_id": correlation_id,
    }
    if cfg.q_keywords:
        payload["q_keywords"] = cfg.q_keywords
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "source.apollo_people.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": payload,
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "apollo"},
    )


register(MANIFEST, execute)
