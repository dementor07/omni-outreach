"""Instagram profile info (LinkFinder)."""

from __future__ import annotations

from app.nodes import register

from ._common import InstagramProfileConfig, make_execute, make_manifest


LINKFINDER_TYPE = "instagram_profile_to_instagram_info"

MANIFEST = make_manifest(
    node_type="linkfinder.instagram_info",
    display_name="Instagram profile info (LinkFinder)",
    summary="Enrich Instagram profile metrics and bio data.",
    config_schema=InstagramProfileConfig,
    icon="instagram",
)

execute = make_execute(LINKFINDER_TYPE, InstagramProfileConfig)

register(MANIFEST, execute)
