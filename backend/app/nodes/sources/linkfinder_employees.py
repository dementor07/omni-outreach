"""LinkFinder company-domain employee finder."""

from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.nodes import NodeCategory, NodeContext, NodeHandle, NodeManifest, NodeResult, SideEffect, register


class LinkFinderEmployeesConfig(BaseModel):
    connection_name: str = Field(min_length=1, description="LinkFinder connection (api_key)")
    domain: str = Field(min_length=1, max_length=255, description="Company domain to search")
    department: str | None = Field(None, max_length=120, description="Optional department filter")
    seniority: str | None = Field(None, max_length=120, description="Optional seniority filter")
    employee_count: int | None = Field(None, ge=1, le=100, description="Optional employee count requested by LinkFinder docs")
    fetch_count: int = Field(25, ge=1, le=100, description="Max employees to request")
    people_key: str = Field("people", min_length=1, description="custom_fields key where the people list lands")


MANIFEST = NodeManifest(
    type="source.linkfinder_employees",
    category=NodeCategory.SOURCE,
    display_name="Company employees (LinkFinder)",
    summary="Find employees for a company domain through LinkFinder",
    config_schema=LinkFinderEmployeesConfig,
    output_handles=(
        NodeHandle("default", "1+ employees found; list lands in custom_fields[people_key]"),
        NodeHandle("empty", "No employees matched"),
        NodeHandle("on_error", "LinkFinder call failed"),
    ),
    capabilities=("connection:linkfinder",),
    side_effect=SideEffect.NETWORK,
    icon="users",
    primary_fields=("connection_name", "domain"),
    advanced_fields=("department", "seniority", "employee_count", "fetch_count", "people_key"),
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkFinderEmployeesConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    payload = {
        "provider": "linkfinder",
        "connection_name": cfg.connection_name,
        "linkfinder_type": "company_domain_to_employees",
        "input_data": cfg.domain,
        "fetch_count": cfg.fetch_count,
        "people_key": cfg.people_key,
        "correlation_id": correlation_id,
    }
    if cfg.department:
        payload["department"] = cfg.department
    if cfg.seniority:
        payload["seniority"] = cfg.seniority
    if cfg.employee_count:
        payload["employee_count"] = cfg.employee_count
    return NodeResult(
        handle="default",
        events=[
            {
                "event_type": "source.linkfinder_employees.requested",
                "entity_type": "lead",
                "entity_id": ctx.lead.get("id"),
                "payload": payload,
            }
        ],
        telemetry={"correlation_id": correlation_id, "provider": "linkfinder", "type": "company_domain_to_employees"},
    )


register(MANIFEST, execute)
