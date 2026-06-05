"""Resolve + dedup the current company against the knowledge graph.

Runs inside a source fan-out loop (one child lead per company from
source.naukri / source.linkedin_jobs). It deduplicates the raw company name
against omni_companies (exact / alias / fuzzy suffix-strip) and branches so the
flow can skip work the KG already did:

  known    — company already has discovered people (people_discovered=true) →
             skip people-discovery entirely (zero cost; the KG is the moat)
  rejected — company was previously screened out → drop
  new      — first time seen (or seen but not yet people-discovered) → continue
             down the discovery path

The actual KG read/write happens in the transition worker (which holds the DB
scope) via app.services.company_kg; the worker injects the resolution into the
lead context as ``custom_fields.company_resolution`` before firing this node —
the same injection pattern as condition.replied. This node stays DB-free and
just selects the handle + emits a company.discovered projection event so the
canonical company id lands on omni_events -> omni_companies.

Absorbed from omni_outreach_v3 resolver.rs / orchestrator company gating.
"""

from __future__ import annotations

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


class ResolveCompanyConfig(BaseModel):
    item_field: str = Field(
        "item",
        description="custom_fields key holding this company's row (set by flow.for_each)",
    )
    min_signal_score: int = Field(
        0,
        ge=0,
        description="Skip people-discovery for companies below this hiring-signal score (0 = no gate)",
    )


MANIFEST = NodeManifest(
    type="crm.resolve_company",
    category=NodeCategory.CRM,
    summary="Dedup the current company against the knowledge graph and branch on what's known",
    config_schema=ResolveCompanyConfig,
    output_handles=(
        NodeHandle("new", "First time seen (or not yet people-discovered) — continue discovery"),
        NodeHandle("known", "KG already has people for this company — skip discovery"),
        NodeHandle("rejected", "Company was previously screened out — drop"),
    ),
    side_effect=SideEffect.MUTATE,
    icon="building",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = ResolveCompanyConfig(**ctx.config)
    cf = ctx.lead.get("custom_fields") or {}
    company_row = cf.get(cfg.item_field) or {}
    # The worker injects the KG resolution result here before firing this node.
    resolution = cf.get("company_resolution") or {}

    company_id = resolution.get("company_id")
    status = resolution.get("screening_status", "pending")
    people_discovered = bool(resolution.get("people_discovered"))
    company_name = resolution.get("name") or company_row.get("company_name") or "Unknown"

    if status == "rejected":
        return NodeResult(
            handle="rejected",
            telemetry={"company": company_name, "status": status, "reason": resolution.get("filter_reason")},
        )

    # Signal gate: a company below the configured hiring-signal threshold isn't
    # worth discovery effort (signal_scorer.rs gating). Treat as rejected.
    signal_score = int(resolution.get("signal_score") or 0)
    if cfg.min_signal_score > 0 and signal_score < cfg.min_signal_score:
        return NodeResult(
            handle="rejected",
            telemetry={"company": company_name, "signal_score": signal_score, "reason": "low_signal"},
        )

    handle = "known" if people_discovered else "new"

    events = []
    if company_id:
        # Project the canonical company (id from the KG resolution) so it lands
        # in omni_companies with the source-row metadata merged in.
        events.append(
            {
                "event_type": "company.discovered",
                "entity_type": "company",
                "entity_id": company_id,
                "payload": {
                    "name": company_name,
                    "industry": company_row.get("industry") or company_row.get("sector"),
                    "domain": company_row.get("company_url") or None,
                    "custom_fields": {
                        "source": company_row.get("source"),
                        "employee_count": company_row.get("employee_count"),
                        "kg_resolution": resolution,
                    },
                },
            }
        )

    return NodeResult(
        handle=handle,
        events=events,
        telemetry={"company": company_name, "status": status, "people_discovered": people_discovered},
    )


register(MANIFEST, execute)
