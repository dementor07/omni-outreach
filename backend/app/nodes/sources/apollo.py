"""Apollo.io lead source — search-by-filter, emit one contact.created per match."""

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


class ApolloSourceConfig(BaseModel):
    connection_name: str = Field(description="Apollo connection name (Settings → Integrations)")
    job_titles: list[str] = Field(default_factory=list, description="Filter by job title")
    seniorities: list[str] = Field(default_factory=list, description="Filter by seniority (e.g. director, vp, owner)")
    industries: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    company_sizes: list[str] = Field(default_factory=list)
    limit: int = Field(50, ge=1, le=500, description="Max contacts to pull per run")


MANIFEST = NodeManifest(
    type="source.apollo",
    category=NodeCategory.SOURCE,
    summary="Pull leads from Apollo.io matching the configured filters",
    config_schema=ApolloSourceConfig,
    output_handles=(
        NodeHandle("default", "Emitted when 1+ contacts matched"),
        NodeHandle("empty", "Apollo returned zero results"),
    ),
    capabilities=("connection:apollo",),
    side_effect=SideEffect.NETWORK,
    icon="apollo",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ApolloSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.apollo.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "connection_name": cfg.connection_name,
                "filters": cfg.model_dump(exclude={"connection_name"}),
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id, "limit": cfg.limit})


register(MANIFEST, execute)
