"""Native Unipile LinkedIn people search (UNIPILE-FULL, native lead-gen).

Fan-out source: runs a Unipile ``POST /linkedin/search`` from a seat and writes
the deduped people list under ``custom_fields[people_key]`` for the downstream
``flow.for_each(people)`` to iterate — the same shape as ``source.serper_people``
/ ``source.linkfinder_leads``. This is native LinkedIn lead-gen (no scraping),
so it needs a Unipile connection + a seat (``unipile_account_id``).
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


class LinkedInSearchConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection (Settings → Integrations)")
    unipile_account_id: str = Field(min_length=1, description="The Unipile seat (account id) that runs the search")
    keywords: str = Field("", description="Free-text LinkedIn search query. Optional when company_field is set.")
    company_field: str = Field(
        "",
        description="custom_fields key holding the company dict — searches THAT company's people by name "
        "(per-lead, inside a for_each). Scopes the search to real employees instead of a global title match. "
        "Combined with keywords when both are set (e.g. keywords='marketing' → 'Acme marketing').",
    )
    fetch_count: int = Field(25, ge=1, le=100, description="Max profiles to return")
    people_key: str = Field("people", min_length=1, description="custom_fields key where the deduped people list lands")
    search_params: dict = Field(default_factory=dict, description="Optional extra Unipile search facets")


MANIFEST = NodeManifest(
    type="source.linkedin_search",
    category=NodeCategory.SOURCE,
    display_name="LinkedIn search (Unipile)",
    summary="Find people via native LinkedIn search (Unipile) — writes custom_fields[people_key]",
    config_schema=LinkedInSearchConfig,
    output_handles=(
        NodeHandle("default", "1+ people found; list lands in custom_fields[people_key]"),
        NodeHandle("empty", "No people matched"),
        NodeHandle("on_error", "Search call failed"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="users",
    primary_fields=("connection_name", "unipile_account_id", "keywords"),
    advanced_fields=("fetch_count", "people_key", "search_params"),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInSearchConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())

    # Company-scoped mode: pass the company NAME to the muscle, which resolves it
    # to a LinkedIn company id and scopes the people search to that company's real
    # employees via the structured `company` facet — NOT a fuzzy name keyword.
    # That's the difference between "Zylu's co-founder" and a random person whose
    # name happens to contain the company term. `keywords` stays the ROLE filter
    # (e.g. "marketing"), applied within the company.
    company_name = ""
    if cfg.company_field:
        company = (ctx.lead.get("custom_fields") or {}).get(cfg.company_field) or {}
        company_name = (company.get("company_name") or company.get("name") or "").strip()
    if not company_name and not cfg.keywords.strip():
        # No company to scope to AND no static keywords — end this branch honestly
        # rather than firing an empty, everyone-matches search.
        return NodeResult(handle="empty", telemetry={"correlation_id": correlation_id, "reason": "no query"})

    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "source.linkedin_search.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "unipile",
                    "connection_name": cfg.connection_name,
                    "unipile_account_id": cfg.unipile_account_id,
                    "keywords": cfg.keywords,
                    "company_name": company_name,
                    "fetch_count": cfg.fetch_count,
                    "people_key": cfg.people_key,
                    "search_params": cfg.search_params,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "unipile"},
    )


register(MANIFEST, execute)
