"""Outbound email channel node.

This Python node is a thin shim: it validates the config, redeems the
workspace's email ``connection`` into a one-shot credential ref, and
publishes an ``ActionCommand`` envelope onto the ``outreach.commands``
Kafka topic. The Rust muscle's ``handle_email`` consumes the envelope,
sends via SMTP, and publishes the result back to ``outreach.results``,
which lands on the events stream via the sync worker.

Operators never see SMTP details in their workflow config — they pick
which connection to use by name on the integrations page.
"""

from __future__ import annotations

import logging
import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)

log = logging.getLogger(__name__)


class EmailChannelConfig(BaseModel):
    connection_name: str | None = Field(None, description="Name of the email connection (configured on Settings → Integrations)")
    sending_account_id: str | None = None
    account_pool: Literal["campaign", "round_robin", "single"] | None = None
    subject_template: str = Field(description="Subject with {{contact.first_name}}-style variables")
    body_template: str = Field(description="HTML body with {{contact.first_name}}-style variables")
    from_address: EmailStr | None = Field(None, description="Override the connection's default From address")
    verification_policy: Literal[
        "off", "block_invalid", "require_safe", "require_verified"
    ] = Field(
        "block_invalid",
        description=(
            "off: skip verification; block_invalid: stop known-invalid addresses; "
            "require_safe: require syntax+MX with no risk flags; require_verified: "
            "require mailbox-level verification from a trusted provider"
        ),
    )


MANIFEST = NodeManifest(
    type="channel.email",
    category=NodeCategory.CHANNEL,
    summary="Send an email to a contact via a workspace SMTP connection",
    config_schema=EmailChannelConfig,
    output_handles=(
        NodeHandle("sent", "Message accepted by the SMTP server"),
        NodeHandle("on_error", "Permanent send failure (invalid recipient, auth, etc.)"),
    ),
    capabilities=("connection:smtp",),
    side_effect=SideEffect.NETWORK,
    icon="mail",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = EmailChannelConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())

    # Emit the channel.email.queued intent. The transition worker publishes it
    # to omni.events; the dispatcher routes channel.email -> ChannelType.EMAIL ->
    # the Rust muscle's handle_email (SMTP send). The node stays a pure shim —
    # it renders config + reports intent; the muscle owns the network call.
    events = [
        {
            "event_type": "channel.email.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "subject_template": cfg.subject_template,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="sent", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
