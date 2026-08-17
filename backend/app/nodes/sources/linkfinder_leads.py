"""LinkFinder AI natural-language lead finder."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.nodes import NodeCategory, NodeContext, NodeHandle, NodeManifest, NodeResult, SideEffect, register


class LinkFinderLeadsConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="LinkFinder connection (api_key)")
    query: str = Field(min_length=1, description="Natural-language audience query")
    fetch_count: int = Field(25, ge=1, le=100, description="Max profiles to request")
    people_key: str = Field("people", min_length=1, description="custom_fields key where the people list lands")


MANIFEST = NodeManifest(
    type="source.linkfinder_leads",
    category=NodeCategory.SOURCE,
    display_name="Leads finder (LinkFinder)",
    summary="Find many people from a natural-language LinkFinder query",
    config_schema=LinkFinderLeadsConfig,
    output_handles=(
        NodeHandle("default", "1+ people found; list lands in custom_fields[people_key]"),
        NodeHandle("empty", "No people matched"),
        NodeHandle("on_error", "LinkFinder call failed"),
    ),
    capabilities=("connection:linkfinder",),
    side_effect=SideEffect.NETWORK,
    icon="users",
    primary_fields=("connection_name", "query"),
    advanced_fields=("fetch_count", "people_key"),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkFinderLeadsConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "source.linkfinder_leads.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "linkfinder",
                    "connection_name": cfg.connection_name,
                    "linkfinder_type": "leads_finder_ai",
                    "input_data": cfg.query,
                    "fetch_count": cfg.fetch_count,
                    "people_key": cfg.people_key,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "linkfinder", "type": "leads_finder_ai"},
    )


register(MANIFEST, execute)
