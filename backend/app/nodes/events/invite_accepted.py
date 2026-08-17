"""Pause the lead until a LinkedIn connection invite is accepted (EVENT-PARK-001).

Parks the lead. Released by either:

  * the ACCEPTED signal — the Unipile webhook (routers/webhooks_in.py) calls
    ``services.event_resume.resume_on_signal(..., "invite_accepted")`` which
    emits a transition on the ``accepted`` handle if THIS lead is parked here;
  * the TIMEOUT — a delayed transition on the ``timeout`` handle after
    ``timeout_hours`` (default one week), scheduled by the transition worker from
    the ``timeout_seconds`` telemetry, so an unaccepted invite still advances.
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


class InviteAcceptedConfig(BaseModel):
    timeout_hours: int = Field(168, ge=1, le=720, description="Advance on the timeout handle if the invite is not accepted (default 1 week)")


MANIFEST = NodeManifest(
    type="event.invite_accepted",
    category=NodeCategory.EVENT,
    summary="Pause the lead until a LinkedIn connection invite is accepted (or a timeout)",
    config_schema=InviteAcceptedConfig,
    output_handles=(
        NodeHandle("accepted", "The lead accepted the connection invite"),
        NodeHandle("timeout", "The lead did not accept within the timeout window"),
    ),
    side_effect=SideEffect.READ,
    icon="user-check",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = InviteAcceptedConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="timeout",  # nominal; park=True means the worker doesn't route on it
        park=True,
        telemetry={
            "correlation_id": correlation_id,
            "parked": True,
            "reason": "await_invite_accepted",
            "timeout_seconds": cfg.timeout_hours * 3600,
        },
    )


register(MANIFEST, execute)
