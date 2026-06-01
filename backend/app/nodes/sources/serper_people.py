"""Per-company Serper LinkedIn profile search — interior fan-out enabler.

Searches Google (via Serper) for LinkedIn profiles matching decision-maker
titles at one company. Emits a list under ``custom_fields[people_key]`` that
the downstream ``flow.for_each`` iterates one person at a time.

This is *not* a single HTTP call — it runs 2 query patterns per role, dedupes
URLs across patterns, and stops at ``max_per_company``. Multi-call orchestration
that does not fit ``http_node``. Worker side: a bespoke handler (or follow-up
generic "http_call with per-pattern loop").

Ported from scraper/serper_client.py:58-151.
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


class SerperPeopleSourceConfig(BaseModel):
    connection_name: str = Field(description="Serper connection (Settings -> Integrations)")
    company_field: str = Field(
        "item",
        description="custom_fields key holding the company dict whose name we search for "
        "(default 'item' — what flow.for_each writes per child)",
    )
    titles: list[str] = Field(
        default_factory=lambda: ["CEO", "Founder", "Co-Founder", "CMO"],
        description="Decision-maker titles to search at the company",
    )
    max_per_company: int = Field(5, ge=1, le=50, description="Cap profiles returned per company")
    people_key: str = Field(
        "people",
        description="custom_fields key where the deduped profile list lands",
    )


MANIFEST = NodeManifest(
    type="source.serper_people",
    category=NodeCategory.SOURCE,
    summary="Find LinkedIn profiles at a company via Serper (for downstream for_each)",
    config_schema=SerperPeopleSourceConfig,
    output_handles=(
        NodeHandle("default", "1+ profiles found; list lands in custom_fields[people_key]"),
        NodeHandle("empty", "No profiles matched"),
        NodeHandle("on_error", "Serper call failed"),
    ),
    capabilities=("connection:serper",),
    side_effect=SideEffect.NETWORK,
    icon="users",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = SerperPeopleSourceConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    company = (ctx.lead.get("custom_fields") or {}).get(cfg.company_field) or {}
    events = [
        {
            "event_type": "source.serper_people.requested",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "company_name": company.get("company_name"),
                "industry": company.get("sector") or company.get("industry"),
                "titles": cfg.titles,
                "max_per_company": cfg.max_per_company,
                "people_key": cfg.people_key,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
