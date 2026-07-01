"""Provider-backed person enrichment.

This is the executable stage used by the canvas' enrichment-stack building
block. Each stage owns exactly one provider credential. Multiple stages are
materialised as ordinary DAG nodes so retries, errors, credentials, and
provenance remain visible instead of being hidden inside a bespoke side path.
"""

from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


LinkFinderEnrichType = Literal[
    # Live LinkFinder docs, 2026-07-01.
    "linkedin_profile_to_email",
    "linkedin_profile_to_phone",
    "linkedin_profile_to_linkedin_info",
    "email_to_linkedin_url",
    "email_to_profile",
    "email_to_phone",
    "phone_to_linkedin_url",
    "phone_to_profile",
    "phone_to_email",
    "lead_full_name_to_linkedin_url",
    "company_name_to_website",
    "company_name_to_phone",
    "company_name_to_email",
    "company_name_to_employee_count",
    "company_name_to_linkedin_url",
    "linkedin_company_to_linkedin_info",
    "linkedin_company_to_employee_count",
    "instagram_profile_to_instagram_info",
    # Brief compatibility aliases; Rust normalizes these before calling LinkFinder.
    "linkedin_url_to_email",
    "linkedin_url_to_phone",
    "linkedin_url_to_profile",
    "name_and_company_to_email",
    "name_and_company_to_linkedin",
    "name_and_company_to_profile",
    "domain_to_company_profile",
    "company_name_to_domain",
    "linkedin_company_url_to_profile",
]


class AiEnrichConfig(BaseModel):
    enrich_source: Literal["apollo", "hunter", "proxycurl", "linkfinder"] = Field(
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
    company_name: str | None = Field(
        None,
        max_length=255,
        description="Optional company name override for company-name LinkFinder lookups",
    )
    linkfinder_type: LinkFinderEnrichType | None = Field(
        None,
        description="Which LinkFinder lookup this stage runs. Required when enrich_source='linkfinder'.",
    )

    @model_validator(mode="after")
    def _linkfinder_type_required(self) -> "AiEnrichConfig":
        if self.enrich_source == "linkfinder" and not self.linkfinder_type:
            raise ValueError("linkfinder_type is required when enrich_source='linkfinder'")
        return self


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
    capabilities=("connection:apollo", "connection:hunter", "connection:proxycurl", "connection:linkfinder"),
    side_effect=SideEffect.NETWORK,
    icon="database-zap",
    primary_fields=("enrich_source", "connection_name"),
    advanced_fields=("merge_policy", "skip_if_complete", "domain", "company_name", "linkfinder_type"),
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
    if cfg.company_name:
        payload["company_name"] = cfg.company_name
    if cfg.linkfinder_type:
        payload["linkfinder_type"] = cfg.linkfinder_type

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
