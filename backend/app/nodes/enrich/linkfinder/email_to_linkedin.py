"""Email to LinkedIn (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import LinkFinderBaseConfig, make_execute, make_manifest


LINKFINDER_TYPE = "email_to_linkedin_url"

MANIFEST = make_manifest(
    node_type="linkfinder.email_to_linkedin",
    display_name="Email to LinkedIn (LinkFinder)",
    summary="Find the current lead LinkedIn URL from email.",
    config_schema=LinkFinderBaseConfig,
    icon="mail-search",
)

execute = make_execute(LINKFINDER_TYPE, LinkFinderBaseConfig)

register(MANIFEST, execute)
