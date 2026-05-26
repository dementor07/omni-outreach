"""ProductHunt source — pull makers from posts matching topic/date filters."""

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


class ProductHuntSourceConfig(BaseModel):
    connection_name: str = Field(description="ProductHunt OAuth connection (Settings → Integrations)")
    topic_slugs: list[str] = Field(default_factory=list, description="Filter posts by topic slug (e.g. saas, developer-tools)")
    posted_within_days: int = Field(30, ge=1, le=365, description="Only posts launched in the last N days")
    min_upvotes: int = Field(50, ge=0)
    limit: int = Field(50, ge=1, le=200)


MANIFEST = NodeManifest(
    type="source.producthunt",
    category=NodeCategory.SOURCE,
    summary="Pull makers + commenters from recent ProductHunt launches",
    config_schema=ProductHuntSourceConfig,
    output_handles=(
        NodeHandle("default", "Emitted when 1+ makers found"),
        NodeHandle("empty", "No posts matched the filters"),
    ),
    capabilities=("connection:producthunt",),
    side_effect=SideEffect.NETWORK,
    icon="producthunt",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ProductHuntSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.producthunt.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "connection_name": cfg.connection_name,
                "filters": cfg.model_dump(exclude={"connection_name"}),
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
