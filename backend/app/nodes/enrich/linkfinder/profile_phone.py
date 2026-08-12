"""Phone from LinkedIn (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import LinkFinderBaseConfig, make_execute, make_manifest

LINKFINDER_TYPE = "linkedin_profile_to_phone"

MANIFEST = make_manifest(
    node_type="linkfinder.profile_phone",
    display_name="Phone from LinkedIn (LinkFinder)",
    summary="Find a phone number for the current lead from their LinkedIn profile URL.",
    config_schema=LinkFinderBaseConfig,
    icon="phone",
)

execute = make_execute(LINKFINDER_TYPE, LinkFinderBaseConfig)

register(MANIFEST, execute)
