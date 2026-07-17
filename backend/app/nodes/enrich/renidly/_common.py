"""Shared factory for first-class Renidly enrichment nodes.

Renidly is an identity graph: one key, one header, one response envelope across
every endpoint. Each node here pins a single ``renidly_mode``; the muscle
(``handlers/enrich.rs::renidly``) turns that mode into the endpoint + query
params and normalises the envelope back onto the lead.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
)


class RenidlyBaseConfig(BaseModel):
    connection_name: str = Field(min_length=1, max_length=200, description="Renidly connection (api_key)")


class PersonProfileConfig(RenidlyBaseConfig):
    handle: str | None = Field(
        None,
        max_length=200,
        description="Optional LinkedIn handle override; defaults to the handle in the lead's LinkedIn URL",
    )
    renidly_id: str | None = Field(
        None,
        max_length=64,
        description="Optional Renidly person id (prsn_…) — an exact-record lookup that beats the handle",
    )


# Config keys forwarded to the muscle as lookup inputs. Keep in step with
# `renidly_request_for` in handlers/enrich.rs.
_INPUT_FIELDS = ("handle", "renidly_id")


def make_manifest(
    *,
    node_type: str,
    display_name: str,
    summary: str,
    config_schema: type[BaseModel],
    icon: str = "user-search",
) -> NodeManifest:
    return NodeManifest(
        type=node_type,
        category=NodeCategory.ENRICH,
        display_name=display_name,
        summary=summary,
        config_schema=config_schema,
        output_handles=(
            NodeHandle("default", "Renidly finished; continue with enriched data"),
            NodeHandle("on_error", "Renidly failed; continue through the fallback route"),
        ),
        capabilities=("connection:renidly",),
        side_effect=SideEffect.NETWORK,
        icon=icon,
        primary_fields=("connection_name",),
        advanced_fields=tuple(field for field in _INPUT_FIELDS if field in config_schema.model_fields),
        visible_in_palette=True,
    )


def make_execute(renidly_mode: str, config_schema: type[BaseModel]):
    async def execute(ctx: NodeContext) -> NodeResult:
        cfg = config_schema(**ctx.config)
        correlation_id = ctx.correlation_id or str(uuid.uuid4())
        payload: dict[str, Any] = {
            "enrich_source": "renidly",
            "connection_name": cfg.connection_name,
            "renidly_mode": renidly_mode,
            "correlation_id": correlation_id,
            "node_id": ctx.node_id,
            "lead_id": ctx.lead.get("id"),
        }
        for key in _INPUT_FIELDS:
            value = getattr(cfg, key, None)
            if value:
                payload[key] = value
        return NodeResult(
            handle="default",
            events=[
                {
                    "event_type": "ai.enrich.requested",
                    "entity_type": "lead",
                    "entity_id": ctx.lead.get("id"),
                    "payload": payload,
                }
            ],
            telemetry={"correlation_id": correlation_id, "provider": "renidly", "mode": renidly_mode},
        )

    return execute
