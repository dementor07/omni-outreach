"""LinkedIn direct message via Unipile (muscle: handle_linkedin_dm)."""

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


class LinkedInDmConfig(LinkedInActionConfig):
    message_template: str = Field(
        min_length=1,
        description="Message body; supports {{contact.first_name}}-style variables",
    )


MANIFEST = NodeManifest(
    type="channel.linkedin_dm",
    category=NodeCategory.CHANNEL,
    summary="Send a LinkedIn direct message via Unipile",
    config_schema=LinkedInDmConfig,
    output_handles=(
        NodeHandle("sent", "Message accepted by Unipile"),
        NodeHandle("on_error", "Permanent failure (account limit, blocked profile, …)"),
        # RELGATE-001: a DM to a non-1st-degree connection is held here instead
        # of burning a 403.
        NodeHandle("not_connected", "DM held — recipient is not a connection yet"),
        # NOCHAT-001: a DM opened a chat but Unipile returned no chat_id — the
        # send happened but the thread can't be followed up; degraded path.
        NodeHandle("no_thread", "DM sent but no chat thread to follow up on"),
        # DEDUP-SEND-001: this contact was already messaged on this channel (per
        # the node's dedupe_action/scope) — the send was skipped, continue here.
        NodeHandle("already_messaged", "Skipped — this contact was already messaged"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="linkedin",
    # OUTBOUND-FIRST-001: DMing a known (connected) audience can START a campaign.
    can_be_entry=True,
)


execute = make_execute("dm", LinkedInDmConfig, ("message_template",))

register(MANIFEST, execute)
