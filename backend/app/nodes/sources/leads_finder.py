"""LinkFinder AI lead discovery source.

Runs the fan-out LinkFinder endpoints that return many people and writes the
normalised list under ``custom_fields[people_key]`` for ``flow.for_each``.
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


class LeadsFinderSourceConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="LinkFinder connection (api_key)")
    finder_type: Literal["leads_finder_ai", "company_domain_to_employees", "linkedin_post_to_reactions"]
    input_data: str = Field(min_length=1, description="Natural-language query, company domain, or LinkedIn post URL")
    fetch_count: int = Field(25, ge=1, le=100, description="Max people/profiles to request")
    people_key: str = Field("people", min_length=1, description="custom_fields key where the people list lands")


MANIFEST = NodeManifest(
    type="source.leads_finder",
    category=NodeCategory.SOURCE,
    summary="Find people through LinkFinder AI and write them to custom_fields[people_key]",
    config_schema=LeadsFinderSourceConfig,
    output_handles=(
        NodeHandle("default", "1+ people found; list lands in custom_fields[people_key]"),
        NodeHandle("empty", "No people matched"),
        NodeHandle("on_error", "LinkFinder call failed"),
    ),
    capabilities=("connection:linkfinder",),
    side_effect=SideEffect.NETWORK,
    icon="users",
    primary_fields=("connection_name", "finder_type", "input_data"),
    advanced_fields=("fetch_count", "people_key"),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LeadsFinderSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "source.leads_finder.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "linkfinder",
                    "connection_name": cfg.connection_name,
                    "linkfinder_type": cfg.finder_type,
                    "input_data": cfg.input_data,
                    "fetch_count": cfg.fetch_count,
                    "people_key": cfg.people_key,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "linkfinder", "type": cfg.finder_type},
    )


register(MANIFEST, execute)
