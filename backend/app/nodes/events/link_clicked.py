"""Pause the lead until a tracked link is clicked (EVENT-PARK-001).

Parks the lead. Released by either:

  * the CLICK signal — when the recipient clicks a tracked link, the redirect
    endpoint (routers/tracking.py) calls
    ``services.event_resume.resume_on_signal(..., "link_clicked")`` which emits a
    transition on the ``clicked`` handle if THIS lead is parked here;
  * the TIMEOUT — a delayed transition on the ``timeout`` handle after
    ``timeout_hours``, scheduled by the transition worker from the
    ``timeout_seconds`` telemetry, so a never-clicked link still advances.
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


class LinkClickedConfig(BaseModel):
    timeout_hours: int = Field(72, ge=1, le=720, description="Advance on the timeout handle if no link is clicked within this window")


MANIFEST = NodeManifest(
    type="event.link_clicked",
    category=NodeCategory.EVENT,
    summary="Pause the lead until a link is clicked (or a timeout)",
    config_schema=LinkClickedConfig,
    output_handles=(
        NodeHandle("clicked", "The lead clicked a link"),
        NodeHandle("timeout", "The lead did not click a link within the timeout window"),
    ),
    side_effect=SideEffect.READ,
    icon="mouse-pointer",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = LinkClickedConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    return NodeResult(
        handle="timeout",  # nominal; park=True means the worker doesn't route on it
        park=True,
        telemetry={
            "correlation_id": correlation_id,
            "parked": True,
            "reason": "await_link_clicked",
            "timeout_seconds": cfg.timeout_hours * 3600,
        },
    )


register(MANIFEST, execute)
