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
    keywords: str = Field(min_length=1, description="Free-text LinkedIn search query")
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
