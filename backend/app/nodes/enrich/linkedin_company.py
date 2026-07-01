"""LinkedIn company profile enrichment (Unipile GET /linkedin/company/{id}).

Fetches a company's LinkedIn profile via a Unipile seat and merges the fields it
finds (name/industry/website/size/HQ) into the lead as an ``enrichment`` envelope
(the transition worker's ``_apply_enrichment_mutation`` whitelists them). Needs a
Unipile connection + seat + the target company_id.
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


class LinkedInCompanyProfileConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Unipile connection")
    unipile_account_id: str = Field(min_length=1, description="Unipile seat (account id)")
    company_id_field: str = Field(
        "company_id",
        description="custom_fields key holding the LinkedIn company id to look up",
    )


MANIFEST = NodeManifest(
    type="enrich.linkedin_company",
    category=NodeCategory.ENRICH,
    display_name="LinkedIn company profile (Unipile)",
    summary="Enrich the lead with a company's LinkedIn profile via Unipile",
    config_schema=LinkedInCompanyProfileConfig,
    output_handles=(
        NodeHandle("default", "Company profile fetched; fields merged onto the lead"),
        NodeHandle("on_error", "Lookup failed"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="building-2",
    primary_fields=("connection_name", "unipile_account_id"),
    advanced_fields=("company_id_field",),
    visible_in_palette=False,
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkedInCompanyProfileConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    cf = ctx.lead.get("custom_fields") or {}
    company_id = cf.get(cfg.company_id_field) or ctx.config.get("company_id")
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "enrich.linkedin_company.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "unipile",
                    "connection_name": cfg.connection_name,
                    "unipile_account_id": cfg.unipile_account_id,
                    "company_id": company_id,
                    "correlation_id": correlation_id,
                    "node_id": ctx.node_id,
                    "lead_id": ctx.lead.get("id"),
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "unipile"},
    )


register(MANIFEST, execute)
