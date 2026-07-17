"""LinkedIn InMail via Unipile (muscle: handle_linkedin_inmail).

InMail is its own product, not a DM variant: it reaches OUTSIDE the network
(no relationship gate applies — that is the point of paying for it), takes a
subject line, and posts to Unipile's dedicated /api/v1/inmails endpoint.
"""

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


class LinkedInInMailConfig(LinkedInActionConfig):
    subject_template: str = Field(
        min_length=1,
        description="InMail subject; supports {{contact.first_name}}-style variables",
    )
    message_template: str = Field(
        min_length=1,
        description="InMail body; supports {{contact.first_name}}-style variables",
    )


MANIFEST = NodeManifest(
    type="channel.linkedin_inmail",
    category=NodeCategory.CHANNEL,
    summary="Send a LinkedIn InMail (out-of-network message) via Unipile",
    config_schema=LinkedInInMailConfig,
    output_handles=(
        NodeHandle("sent", "InMail accepted by Unipile"),
        NodeHandle("on_error", "Permanent failure (no InMail credits, blocked profile, …)"),
        # DEDUP-SEND-001: this contact was already messaged on this channel (per
        # the node's dedupe_action/scope) — the send was skipped, continue here.
        NodeHandle("already_messaged", "Skipped — this contact was already messaged"),
    ),
    capabilities=("connection:unipile",),
    side_effect=SideEffect.NETWORK,
    icon="linkedin",
    # OUTBOUND-FIRST-001: InMailing a known audience can START a campaign.
    can_be_entry=True,
)


execute = make_execute("inmail", LinkedInInMailConfig, ("subject_template", "message_template"))

register(MANIFEST, execute)
