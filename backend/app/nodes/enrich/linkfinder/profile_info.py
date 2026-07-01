"""LinkedIn profile info (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import LinkFinderBaseConfig, make_execute, make_manifest


LINKFINDER_TYPE = "linkedin_profile_to_linkedin_info"

MANIFEST = make_manifest(
    node_type="linkfinder.profile_info",
    display_name="LinkedIn profile info (LinkFinder)",
    summary="Enrich the current lead from their LinkedIn profile URL.",
    config_schema=LinkFinderBaseConfig,
    icon="linkedin",
)

execute = make_execute(LINKFINDER_TYPE, LinkFinderBaseConfig)

register(MANIFEST, execute)
