"""Provider-backed person enrichment.

This is the executable stage used by the canvas' enrichment-stack building
block. Each stage owns exactly one provider credential. Multiple stages are
materialised as ordinary DAG nodes so retries, errors, credentials, and
provenance remain visible instead of being hidden inside a bespoke side path.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class AiEnrichConfig(BaseModel):
    enrich_source: Literal["apollo", "hunter", "proxycurl"] = Field(
        description="The provider this stage queries",
    )
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
        description="Avoid a paid provider call when all fields that provider can add are already present",
    )
    domain: str | None = Field(
        None,
        max_length=255,
        description="Optional company domain for Hunter when the contact has no domain",
    )
    # APOLLO-DATA Part 2: Apollo's OWN internal enrichment waterfall. When set
    # (and enrich_source == "apollo"), Apollo waterfalls across its providers to
    # fill email/phone and reveal personal emails. Ignored by other providers.
    # `reveal_phone_number` is intentionally absent — it needs a webhook_url +
    # async poll (documented follow-up).
    run_waterfall_email: bool = Field(
        False,
        description="Apollo only: run Apollo's internal email waterfall to fill a missing email",
    )
    run_waterfall_phone: bool = Field(
        False,
        description="Apollo only: run Apollo's internal phone waterfall to fill a missing phone",
    )
    reveal_personal_emails: bool = Field(
        False,
        description="Apollo only: reveal the contact's personal emails (consumes Apollo credits)",
    )

MANIFEST = NodeManifest(
    type="ai.enrich",
    category=NodeCategory.ENRICH,
    display_name="Enrichment provider",
    summary="Query one connected data provider and merge the fields it finds with provenance",
    config_schema=AiEnrichConfig,
    output_handles=(
        NodeHandle("default", "Provider finished; continue with the merged contact"),
        NodeHandle("on_error", "Provider failed; continue through the stack fallback"),
    ),
    capabilities=("connection:apollo", "connection:hunter", "connection:proxycurl"),
    side_effect=SideEffect.NETWORK,
    icon="database-zap",
    primary_fields=("enrich_source", "connection_name"),
    advanced_fields=(
        "merge_policy", "skip_if_complete", "domain",
        "run_waterfall_email", "run_waterfall_phone", "reveal_personal_emails",
    ),
    visible_in_palette=False,
)


async def execute(ctx: NodeContext) -> NodeResult:
    try:
        cfg = AiEnrichConfig(**ctx.config)
    except ValidationError:
        return NodeResult(error="ENRICHMENT_STAGE_CONFIG_INVALID")

    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    payload = {
        "enrich_source": cfg.enrich_source,
        "connection_name": cfg.connection_name,
        "merge_policy": cfg.merge_policy,
        "skip_if_complete": cfg.skip_if_complete,
        "correlation_id": correlation_id,
    }
    if cfg.domain:
        payload["domain"] = cfg.domain
    # Apollo's internal waterfall flags only mean anything to the Apollo handler;
    # forward them only for that source so other providers see a clean payload.
    if cfg.enrich_source == "apollo":
        if cfg.run_waterfall_email:
            payload["run_waterfall_email"] = True
        if cfg.run_waterfall_phone:
            payload["run_waterfall_phone"] = True
        if cfg.reveal_personal_emails:
            payload["reveal_personal_emails"] = True
    return NodeResult(
        handle="default",
        events=[
            {
                # ENRICH-INTENT-001: this MUST be a dot-separated ".requested"
                # intent or the dispatcher's _is_intent (endswith ".requested")
                # rejects it and the muscle never runs — enrichment silently
                # no-ops. The old name "lead.enrichment_requested" ends in
                # "_requested" (underscore), so it was NEVER routed. The
                # dispatcher resolves the node from payload.node_id, so the
                # event name only needs to (a) pass _is_intent and (b) carry
                # node_id/lead_id — the node_type drives ChannelType.ENRICH.
                "event_type": "ai.enrich.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {**payload, "node_id": ctx.node_id, "lead_id": ctx.lead.get("id")},
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": cfg.enrich_source},
    )


register(MANIFEST, execute)
