"""Pause the lead until Mailgun confirms delivery (MAILGUN-001).

Unlike SMTP (where the send node's ``sent`` handle only means "the relay accepted
the message"), Mailgun emits a real ``delivered`` webhook when the receiving mail
server accepts the message for the recipient. This node parks the lead for that
confirmation:

  * the DELIVERED signal — Mailgun's ``delivered`` webhook resumes the lead on the
    ``delivered`` handle (proceed with confidence the message landed);
  * the TIMEOUT — no delivery confirmation within ``timeout_hours`` advances the
    lead on ``timeout`` (soft signal: delivery is unconfirmed, e.g. greylisting or
    a webhook miss — continue but treat as lower-confidence).

Mirrors event.email_opened's park/timeout contract. Requires a Mailgun connection
with webhooks configured; there is no delivery-confirmation signal over plain SMTP.
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


class EmailDeliveredConfig(BaseModel):
    timeout_hours: int = Field(
        6, ge=1, le=720,
        description="Advance on 'timeout' (delivery unconfirmed) if no delivered webhook within this window",
    )


MANIFEST = NodeManifest(
    type="event.email_delivered",
    category=NodeCategory.EVENT,
    summary="Pause the lead until Mailgun confirms the email was delivered (or a timeout)",
    config_schema=EmailDeliveredConfig,
    output_handles=(
        NodeHandle("delivered", "The receiving server accepted the message"),
        NodeHandle("timeout", "No delivery confirmation within the window (unconfirmed)"),
    ),
    side_effect=SideEffect.READ,
    icon="mail-check",
    display_name="Wait for delivery",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = EmailDeliveredConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="timeout",  # nominal; park=True means the worker doesn't route on it
        park=True,
        telemetry={
            "correlation_id": correlation_id,
            "parked": True,
            "reason": "await_email_delivered",
            "timeout_seconds": cfg.timeout_hours * 3600,
        },
    )


register(MANIFEST, execute)
