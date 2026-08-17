"""Apollo organization job postings (APOLLO-DATA, hiring signal).

Source: pulls a company's open job postings via Apollo's
``GET /api/v1/organizations/{organization_id}/job_postings`` — a hiring signal
(a company hiring for a role is a buying signal). Writes the postings under
``custom_fields[jobs_key]``.

Apollo's job-postings endpoint needs an ``organization_id``. This node accepts one
directly in config, OR a ``domain`` — in which case the Rust handler first resolves
the org via org-enrich (#5) to get the id, then fetches postings. Emits
``source.apollo_jobs.requested``; the Rust ApolloJobs handler does the work.
"""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field, model_validator

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class ApolloJobsConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="Apollo connection (Settings → Integrations)")
    organization_id: str | None = Field(
        None,
        max_length=64,
        description="Apollo organization id (from an org search/enrich). If unset, provide a domain.",
    )
    domain: str | None = Field(
        None,
        max_length=255,
        description="Company domain — the handler resolves the org id from it via org-enrich when organization_id is unset.",
    )
    domain_field: str = Field(
        "company_domain",
        description="custom_fields key holding the lead's company domain when neither organization_id nor domain is set",
    )
    jobs_key: str = Field(
        "job_postings",
        min_length=1,
        description="custom_fields key where the job-postings list lands",
    )

    @model_validator(mode="after")
    def _require_id_or_domain(self) -> ApolloJobsConfig:
        # The lead may still supply a domain via domain_field at runtime, so a
        # bare config (neither id nor domain) is allowed — the handler falls back
        # to the lead's custom_fields. Nothing to enforce statically here beyond
        # documenting the contract.
        return self


MANIFEST = NodeManifest(
    type="source.apollo_jobs",
    category=NodeCategory.SOURCE,
    display_name="Apollo job postings",
    summary="Pull a company's open roles from Apollo (hiring signal) — writes custom_fields[jobs_key]",
    config_schema=ApolloJobsConfig,
    output_handles=(
        NodeHandle("default", "1+ postings found; list lands in custom_fields[jobs_key]"),
        NodeHandle("empty", "No postings, or the org could not be resolved from the domain"),
        NodeHandle("on_error", "Fetch failed"),
    ),
    capabilities=("connection:apollo",),
    side_effect=SideEffect.NETWORK,
    icon="briefcase",
    primary_fields=("connection_name", "organization_id", "domain"),
    advanced_fields=("domain_field", "jobs_key"),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ApolloJobsConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    cf = ctx.lead.get("custom_fields") or {}
    domain = cfg.domain or cf.get(cfg.domain_field)
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "source.apollo_jobs.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": {
                    "provider": "apollo",
                    "connection_name": cfg.connection_name,
                    "organization_id": cfg.organization_id,
                    "domain": domain,
                    "domain_field": cfg.domain_field,
                    "jobs_key": cfg.jobs_key,
                    "correlation_id": correlation_id,
                },
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "apollo"},
    )


register(MANIFEST, execute)
