"""Company employee count (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import CompanyNameConfig, make_execute, make_manifest


LINKFINDER_TYPE = "company_name_to_employee_count"

MANIFEST = make_manifest(
    node_type="linkfinder.company_employee_count",
    display_name="Company employee count (LinkFinder)",
    summary="Find employee count from a company name.",
    config_schema=CompanyNameConfig,
    icon="users",
)

execute = make_execute(LINKFINDER_TYPE, CompanyNameConfig)

register(MANIFEST, execute)
