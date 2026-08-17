"""Company LinkedIn URL (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import CompanyNameConfig, make_execute, make_manifest

LINKFINDER_TYPE = "company_name_to_linkedin_url"

MANIFEST = make_manifest(
    node_type="linkfinder.company_linkedin",
    display_name="Company LinkedIn URL (LinkFinder)",
    summary="Find a company LinkedIn page from its company name.",
    config_schema=CompanyNameConfig,
    icon="linkedin",
)

execute = make_execute(LINKFINDER_TYPE, CompanyNameConfig)

register(MANIFEST, execute)
