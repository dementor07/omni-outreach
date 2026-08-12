"""Company phone (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import CompanyNameConfig, make_execute, make_manifest

LINKFINDER_TYPE = "company_name_to_phone"

MANIFEST = make_manifest(
    node_type="linkfinder.company_phone",
    display_name="Company phone (LinkFinder)",
    summary="Find a company phone number from its company name.",
    config_schema=CompanyNameConfig,
    icon="phone",
)

execute = make_execute(LINKFINDER_TYPE, CompanyNameConfig)

register(MANIFEST, execute)
