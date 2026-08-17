"""Shared base for the first-class person-enrichment provider nodes.

One provider = one node (the rule locked when ``source.agency`` was split):
Apollo person-match, Hunter email-finder, and Proxycurl profile enrichment are
different products with different inputs and outputs, so each is its own node.
The old combined ``ai.enrich`` (an ``enrich_source`` toggle) is gone; migration
053 rewrites stored graphs onto these types.

All three still emit the SHARED ``ai.enrich.requested`` intent with
``enrich_source`` stamped in the payload — ``handle_enrich`` in the Rust muscle
switches on that field, exactly as the linkfinder/renidly node families do, so
the muscle needs zero change.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.nodes import NodeContext, NodeResult


class EnrichProviderConfig(BaseModel):
    connection_name: str = Field(
        min_length=1,
        max_length=200,
        description="Connected account whose credential this stage uses",
    )
    merge_policy: Literal["fill_missing", "overwrite"] = Field(
        "fill_missing",
        description="Keep existing contact data, or deliberately replace it with this provider",
    )
    skip_if_complete: bool = Field(
        True,
        description="Avoid a paid provider call when all fields this provider can add are already present",
    )


def make_execute(enrich_source: str, config_schema: type[EnrichProviderConfig], passthrough_fields: tuple[str, ...]):
    """Execute fn for one provider node. ``passthrough_fields`` are provider-
    specific config fields forwarded into the payload only when truthy (the
    Apollo waterfall flags, Hunter's domain override)."""

    async def execute(ctx: NodeContext) -> NodeResult:
        cfg = config_schema(**ctx.config)
        correlation_id = ctx.correlation_id or str(uuid.uuid4())
        payload: dict[str, Any] = {
            "enrich_source": enrich_source,
            "connection_name": cfg.connection_name,
            "merge_policy": cfg.merge_policy,
            "skip_if_complete": cfg.skip_if_complete,
            "correlation_id": correlation_id,
            "node_id": ctx.node_id,
            "lead_id": ctx.lead.get("id"),
        }
        for field in passthrough_fields:
            value = getattr(cfg, field, None)
            if value:
                payload[field] = value
        return NodeResult(
            handle="default",
            events=[
                {
                    # ENRICH-INTENT-001: MUST be a dot-separated ".requested"
                    # intent or the dispatcher's _is_intent rejects it and the
                    # muscle never runs.
                    "event_type": "ai.enrich.requested",
                    "entity_type": "lead",
                    "entity_id": ctx.lead.get("id"),
                    "payload": payload,
                }
            ],
            telemetry={"correlation_id": correlation_id, "provider": enrich_source},
        )

    return execute
