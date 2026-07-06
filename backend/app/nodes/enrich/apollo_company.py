"""Apollo company enrichment by domain (APOLLO-DATA).

Enrichment read: takes the lead's company domain and enriches it via Apollo's
``GET /api/v1/organizations/enrich?domain=`` — writing name/industry/employee
count/website/LinkedIn onto the lead as an ``enrichment`` envelope (the transition
worker's ``_apply_enrichment_mutation`` whitelists them). Needs an Apollo
connection (api_key).

The domain comes from node config ``domain`` if set, else the lead's
``custom_fields[domain_field]`` (default ``company_domain``). Emits
``enrich.apollo_company.requested``; the Rust ApolloCompanyEnrich handler
(handlers/apollo_data.rs) performs the read.
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


class ApolloCompanyConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Apollo connection (Settings → Integrations)")
    domain: str | None = Field(
        None,
        max_length=255,
        description="Company domain to enrich (no www/@). Falls back to the lead's custom_fields[domain_field].",
    )
    domain_field: str = Field(
        "company_domain",
        description="custom_fields key holding the lead's company domain when 'domain' is not set",
    )


MANIFEST = NodeManifest(
    type="enrich.apollo_company",
    category=NodeCategory.ENRICH,
    display_name="Apollo company enrich",
    summary="Enrich the lead with Apollo's company profile by domain",
    config_schema=ApolloCompanyConfig,
    output_handles=(
        NodeHandle("default", "Company enriched; fields merged onto the lead"),
        NodeHandle("on_error", "Lookup failed or no domain to enrich"),
    ),
    capabilities=("connection:apollo",),
    side_effect=SideEffect.NETWORK,
    icon="building-2",
    primary_fields=("connection_name",),
    advanced_fields=("domain", "domain_field"),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ApolloCompanyConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    cf = ctx.lead.get("custom_fields") or {}
    domain = cfg.domain or cf.get(cfg.domain_field)
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "enrich.apollo_company.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "apollo",
                    "connection_name": cfg.connection_name,
                    "domain": domain,
                    "domain_field": cfg.domain_field,
                    "correlation_id": correlation_id,
                    "node_id": ctx.node_id,
                    "lead_id": ctx.lead.get("id"),
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "apollo"},
    )


register(MANIFEST, execute)
