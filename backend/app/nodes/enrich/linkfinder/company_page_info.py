"""LinkedIn company info (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import LinkedinCompanyUrlConfig, make_execute, make_manifest


LINKFINDER_TYPE = "linkedin_company_to_linkedin_info"

MANIFEST = make_manifest(
    node_type="linkfinder.company_page_info",
    display_name="LinkedIn company info (LinkFinder)",
    summary="Enrich company data from a LinkedIn company page URL.",
    config_schema=LinkedinCompanyUrlConfig,
    icon="linkedin",
)

execute = make_execute(LINKFINDER_TYPE, LinkedinCompanyUrlConfig)

register(MANIFEST, execute)
