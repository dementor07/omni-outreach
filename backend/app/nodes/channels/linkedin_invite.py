"""LinkedIn connection invite via Unipile (muscle: handle_linkedin_invite)."""

from __future__ import annotations

from pydantic import Field

from app.nodes import (
    NodeCategory,
    NodeHandle,
    NodeManifest,
    SideEffect,
    register,
)
from app.nodes.channels._linkedin_common import LinkedInActionConfig, make_execute


class LinkedInInviteConfig(LinkedInActionConfig):
    message_template: str | None = Field(
        None,
        description="Optional invite note (LinkedIn caps notes at ~300 chars; free seats 200); supports {{contact.first_name}}-style variables",
    )


MANIFEST = NodeManifest(
    type="channel.linkedin_invite",
    category=NodeCategory.CHANNEL,
    summary="Send a LinkedIn connection invite via Unipile",
    config_schema=LinkedInInviteConfig,
    output_handles=(
        NodeHandle("sent", "Invite accepted by Unipile"),
        NodeHandle("on_error", "Permanent failure (account limit, blocked profile, …)"),
        # SMART-INVITE-001: an invite to an existing 1st-degree connection is
        # skipped and routed here so the sequence navigates straight to the next
        # step (no redundant invite, no parking at await-acceptance).
        NodeHandle("already_connected", "Invite skipped — recipient is already a connection"),
        # DEDUP-SEND-001: this contact was already messaged on this channel (per
        # the node's dedupe_action/scope) — the send was skipped, continue here.
        NodeHandle("already_messaged", "Skipped — this contact was already messaged"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="linkedin",
    # OUTBOUND-FIRST-001: inviting a known audience can START a campaign.
    can_be_entry=True,
)


execute = make_execute("invite", LinkedInInviteConfig, ("message_template",))

register(MANIFEST, execute)
