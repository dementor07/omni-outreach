"""ProxyCurl LinkedIn profile source — enrich by LinkedIn URL."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, HttpUrl

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class ProxyCurlSourceConfig(BaseModel):
    connection_name: str = Field(description="ProxyCurl connection name")
    linkedin_url: HttpUrl = Field(description="LinkedIn profile URL to enrich")
    include_email: bool = Field(False, description="Spend extra credits to surface personal/work emails")


MANIFEST = NodeManifest(
    type="source.proxycurl",
    category=NodeCategory.ENRICH,
    summary="Enrich a contact from their LinkedIn URL via ProxyCurl",
    config_schema=ProxyCurlSourceConfig,
    output_handles=(
        NodeHandle("default", "Profile fetched"),
        NodeHandle("empty", "ProxyCurl returned no profile data"),
    ),
    capabilities=("connection:proxycurl",),
    side_effect=SideEffect.NETWORK,
    icon="linkedin",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ProxyCurlSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.proxycurl.requested",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "linkedin_url": str(cfg.linkedin_url),
                "include_email": cfg.include_email,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
