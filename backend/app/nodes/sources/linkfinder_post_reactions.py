"""LinkFinder LinkedIn post reaction finder."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.nodes import NodeCategory, NodeContext, NodeHandle, NodeManifest, NodeResult, SideEffect, register


class LinkFinderPostReactionsConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="LinkFinder connection (api_key)")
    post_url: str = Field(min_length=1, max_length=500, description="LinkedIn post URL")
    people_key: str = Field("people", min_length=1, description="custom_fields key where the people list lands")


MANIFEST = NodeManifest(
    type="source.linkfinder_post_reactions",
    category=NodeCategory.SOURCE,
    display_name="LinkedIn post reactions (LinkFinder)",
    summary="Find people who reacted to a LinkedIn post through LinkFinder",
    config_schema=LinkFinderPostReactionsConfig,
    output_handles=(
        NodeHandle("default", "1+ reactors found; list lands in custom_fields[people_key]"),
        NodeHandle("empty", "No reactors matched"),
        NodeHandle("on_error", "LinkFinder call failed"),
    ),
    capabilities=("connection:linkfinder",),
    side_effect=SideEffect.NETWORK,
    icon="linkedin",
    primary_fields=("connection_name", "post_url"),
    advanced_fields=("people_key",),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkFinderPostReactionsConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "source.linkfinder_post_reactions.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "linkfinder",
                    "connection_name": cfg.connection_name,
                    "linkfinder_type": "linkedin_post_to_reactions",
                    "input_data": cfg.post_url,
                    "people_key": cfg.people_key,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "linkfinder", "type": "linkedin_post_to_reactions"},
    )


register(MANIFEST, execute)
