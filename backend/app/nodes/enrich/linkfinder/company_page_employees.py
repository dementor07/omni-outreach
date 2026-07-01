"""LinkedIn company employee count (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import LinkedinCompanyUrlConfig, make_execute, make_manifest


LINKFINDER_TYPE = "linkedin_company_to_employee_count"

MANIFEST = make_manifest(
    node_type="linkfinder.company_page_employees",
    display_name="LinkedIn company employee count (LinkFinder)",
    summary="Find employee count from a LinkedIn company page URL.",
    config_schema=LinkedinCompanyUrlConfig,
    icon="users",
)

execute = make_execute(LINKFINDER_TYPE, LinkedinCompanyUrlConfig)

register(MANIFEST, execute)
