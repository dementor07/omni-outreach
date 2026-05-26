"""Hunter.io lead source — domain-based email finder."""

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


class HunterSourceConfig(BaseModel):
    connection_name: str = Field(description="Hunter connection name (Settings → Integrations)")
    domain: str = Field(min_length=1, description="Company domain to search (e.g. stripe.com)")
    department: str | None = Field(None, description="Filter by department (executive, marketing, sales, …)")
    seniority: str | None = Field(None, description="Filter by seniority (junior, senior, executive)")
    limit: int = Field(25, ge=1, le=100)


MANIFEST = NodeManifest(
    type="source.hunter",
    category=NodeCategory.SOURCE,
    summary="Pull verified emails for a company domain from Hunter.io",
    config_schema=HunterSourceConfig,
    output_handles=(
        NodeHandle("default", "Emitted when 1+ emails found"),
        NodeHandle("empty", "Hunter returned zero verified emails"),
    ),
    capabilities=("connection:hunter",),
    side_effect=SideEffect.NETWORK,
    icon="hunter",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = HunterSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.hunter.requested",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "connection_name": cfg.connection_name,
                "filters": cfg.model_dump(exclude={"connection_name"}),
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id, "domain": cfg.domain})


register(MANIFEST, execute)
