"""Company website (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import CompanyNameConfig, make_execute, make_manifest


LINKFINDER_TYPE = "company_name_to_website"

MANIFEST = make_manifest(
    node_type="linkfinder.company_website",
    display_name="Company website (LinkFinder)",
    summary="Find a company website/domain from its company name.",
    config_schema=CompanyNameConfig,
    icon="building-2",
)

execute = make_execute(LINKFINDER_TYPE, CompanyNameConfig)

register(MANIFEST, execute)
