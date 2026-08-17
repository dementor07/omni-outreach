"""Apollo company discovery — Apollo.io organization-search API.

Searches Apollo for organizations matching the keyword ICP and writes the
deduped companies to ``custom_fields[companies_key]`` for ``flow.for_each``.
The Apollo connection (api_key) is OPTIONAL: with no connection the node returns
the ``empty`` handle so it ships before a key exists. Add an Apollo connection
in Settings → Integrations to get real data.

Emits ``source.apollo.requested``; the Rust muscle's APOLLO handler
(handlers/discovery.rs) calls the API and shapes the result.
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

_DEFAULT_TITLES = ["Founder", "CEO", "Co-Founder", "Managing Director", "Growth Head"]


class ApolloSourceConfig(BaseModel):
    query: str = Field(
        min_length=1,
        description="Apollo organization keyword(s), e.g. 'lead generation agency'",
    )
    titles: list[str] = Field(
        default_factory=lambda: list(_DEFAULT_TITLES),
        description="Decision-maker titles propagated to each company for downstream people-discovery",
    )
    max_results: int = Field(25, ge=1, le=200, description="Cap on organizations returned per run")
    companies_key: str = Field(
        "companies",
        description="custom_fields key where the deduped company list lands for flow.for_each",
    )
    connection_name: str | None = Field(
        None,
        description="Apollo connection (Settings → Integrations). Optional — without it the node returns 'empty'.",
    )


MANIFEST = NodeManifest(
    type="source.apollo",
    category=NodeCategory.SOURCE,
    summary="Discover companies via the Apollo.io organization-search API (api_key optional)",
    config_schema=ApolloSourceConfig,
    output_handles=(
        NodeHandle("default", "Organizations discovered; list lands in custom_fields[companies_key]"),
        NodeHandle("empty", "No organizations matched, or no Apollo connection set yet"),
        NodeHandle("on_error", "Apollo API call failed"),
    ),
    # Optional connection — node runs (returns empty) without one. Declared with
    # the '?' suffix so the dispatcher only mints a credential when set.
    capabilities=("connection:apollo?",),
    side_effect=SideEffect.NETWORK,
    icon="building",
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
                "query": cfg.query,
                "titles": cfg.titles,
                "max_results": cfg.max_results,
                "companies_key": cfg.companies_key,
                "connection_name": cfg.connection_name,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
