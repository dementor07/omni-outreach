"""Pause the lead until the tracked email is opened (EVENT-PARK-001).

Parks the lead (``park=True``). Two things can release it:

  * the OPEN signal — when the recipient's mail client fetches the tracking
    pixel, ``routers/tracking.py`` calls ``services.event_resume.resume_on_signal``
    which emits a transition on the ``opened`` handle if THIS lead is parked here;
  * the TIMEOUT — the transition worker schedules a delayed transition on the
    ``timeout`` handle after ``timeout_hours`` (carried in telemetry as
    ``timeout_seconds``), so a never-opened email still advances instead of
    stranding the lead forever.

The node itself does NOT pick a success handle (that would route as if opened on
the spot); it only parks and declares the timeout. The handle is chosen later by
whichever release fires first.
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


class EmailOpenedConfig(BaseModel):
    timeout_hours: int = Field(72, ge=1, le=720, description="Advance on the timeout handle if not opened within this window")


MANIFEST = NodeManifest(
    type="event.email_opened",
    category=NodeCategory.EVENT,
    summary="Pause the lead until the email is opened (or a timeout)",
    config_schema=EmailOpenedConfig,
    output_handles=(
        NodeHandle("opened", "The recipient opened the email"),
        NodeHandle("timeout", "The email was not opened within the timeout window"),
    ),
    side_effect=SideEffect.READ,
    icon="mail-open",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = EmailOpenedConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="timeout",  # nominal; park=True means the worker doesn't route on it
        park=True,
        telemetry={
            "correlation_id": correlation_id,
            "parked": True,
            "reason": "await_email_opened",
            "timeout_seconds": cfg.timeout_hours * 3600,
        },
    )


register(MANIFEST, execute)
