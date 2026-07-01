"""Company email (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import CompanyNameConfig, make_execute, make_manifest


LINKFINDER_TYPE = "company_name_to_email"

MANIFEST = make_manifest(
    node_type="linkfinder.company_email",
    display_name="Company email (LinkFinder)",
    summary="Find a company email from its company name.",
    config_schema=CompanyNameConfig,
    icon="mail",
)

execute = make_execute(LINKFINDER_TYPE, CompanyNameConfig)

register(MANIFEST, execute)
