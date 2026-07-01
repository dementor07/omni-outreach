"""Email from LinkedIn (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import LinkFinderBaseConfig, make_execute, make_manifest


LINKFINDER_TYPE = "linkedin_profile_to_email"

MANIFEST = make_manifest(
    node_type="linkfinder.profile_email",
    display_name="Email from LinkedIn (LinkFinder)",
    summary="Find an email for the current lead from their LinkedIn profile URL.",
    config_schema=LinkFinderBaseConfig,
    icon="mail",
)

execute = make_execute(LINKFINDER_TYPE, LinkFinderBaseConfig)

register(MANIFEST, execute)
