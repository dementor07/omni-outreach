"""Pause the lead until the email hard-bounces (MAILGUN-001).

The omnichannel journey's bounce branch: after Email #1, park here to see whether
the address bounces. Two releases:

  * the BOUNCE signal — Mailgun's ``failed`` (severity=permanent) webhook lands on
    ``routers/webhooks_in.receive_mailgun_webhook``, which calls
    ``services.event_resume.resume_on_signal`` and fires the ``bounced`` handle if
    THIS lead is parked here (so the graph can react: find LinkedIn, switch
    channel, drop the lead);
  * the TIMEOUT — if no bounce arrives within ``timeout_hours``, the address is
    presumed deliverable and the lead advances on ``timeout`` (the happy path —
    "no bounce" means the email landed).

Mirrors event.email_opened's park/timeout contract. Bounce events require a
Mailgun connection with webhooks configured; over plain SMTP only a synchronous
permanent send-failure is observable (email.rs returns EMAIL_SMTP_PERMANENT),
which routes on the send node's on_error handle instead of here.
"""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class EmailBouncedConfig(BaseModel):
    timeout_hours: int = Field(
        24, ge=1, le=720,
        description="Advance on the 'timeout' handle (presumed delivered) if no bounce within this window",
    )


MANIFEST = NodeManifest(
    type="event.email_bounced",
    category=NodeCategory.EVENT,
    summary="Pause the lead until the email hard-bounces (or a timeout = presumed delivered)",
    config_schema=EmailBouncedConfig,
    output_handles=(
        NodeHandle("bounced", "The email hard-bounced (permanent failure — bad address)"),
        NodeHandle("timeout", "No bounce within the window — the address is presumed deliverable"),
    ),
    side_effect=SideEffect.READ,
    icon="mail-x",
    display_name="Wait for bounce",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = EmailBouncedConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="timeout",  # nominal; park=True means the worker doesn't route on it
        park=True,
        telemetry={
            "correlation_id": correlation_id,
            "parked": True,
            "reason": "await_email_bounced",
            "timeout_seconds": cfg.timeout_hours * 3600,
        },
    )


register(MANIFEST, execute)
