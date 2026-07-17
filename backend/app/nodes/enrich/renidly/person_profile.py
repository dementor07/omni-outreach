"""Person profile enrichment (Renidly)."""

from __future__ import annotations

from app.nodes import register

from ._common import PersonProfileConfig, make_execute, make_manifest


RENIDLY_MODE = "person_profile"

MANIFEST = make_manifest(
    node_type="renidly.person_profile",
    display_name="Person profile (Renidly)",
    summary="Enrich the lead's name, headline and location from Renidly's identity graph.",
    config_schema=PersonProfileConfig,
    icon="user-search",
)

execute = make_execute(RENIDLY_MODE, PersonProfileConfig)

register(MANIFEST, execute)
