"""Name to LinkedIn (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import CompanyNameConfig, make_execute, make_manifest

LINKFINDER_TYPE = "lead_full_name_to_linkedin_url"

MANIFEST = make_manifest(
    node_type="linkfinder.name_to_linkedin",
    display_name="Name to LinkedIn (LinkFinder)",
    summary="Find the current lead LinkedIn URL from full name and company.",
    config_schema=CompanyNameConfig,
    icon="user-search",
)

execute = make_execute(LINKFINDER_TYPE, CompanyNameConfig)

register(MANIFEST, execute)
