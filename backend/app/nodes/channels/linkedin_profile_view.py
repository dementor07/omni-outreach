"""LinkedIn profile view via Unipile (muscle: handle_linkedin_profile_view).

The view itself is the outbound side effect (the person sees "viewed your
profile") — a classic warming touch. The muscle also lifts the profile's
headline/company/role/location into custom_fields for free
(UNIPILE-ENRICH-001) and records network_distance for the relationship gate.
"""

from __future__ import annotations

from app.nodes import (
    NodeCategory,
    NodeHandle,
    NodeManifest,
    SideEffect,
    register,
)
from app.nodes.channels._linkedin_common import LinkedInActionConfig, make_execute


class LinkedInProfileViewConfig(LinkedInActionConfig):
    pass


MANIFEST = NodeManifest(
    type="channel.linkedin_profile_view",
    category=NodeCategory.CHANNEL,
    summary="View the lead's LinkedIn profile via Unipile (warming touch + free enrichment)",
    config_schema=LinkedInProfileViewConfig,
    output_handles=(
        NodeHandle("sent", "Profile viewed; distance + profile fields recorded"),
        NodeHandle("on_error", "Permanent failure (profile unavailable, …)"),
        # DEDUP-SEND-001: this contact was already touched on this channel (per
        # the node's dedupe_action/scope) — the view was skipped, continue here.
        NodeHandle("already_messaged", "Skipped — this contact was already messaged"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="linkedin",
    # OUTBOUND-FIRST-001: profile-viewing a known audience can START a campaign
    # (a warming pass before the invite wave).
    can_be_entry=True,
)


execute = make_execute("profile_view", LinkedInProfileViewConfig, ())

register(MANIFEST, execute)
