"""channel.n8n — hand a lead to an n8n workflow (N8N-001 Part 3a).

A friendly PRESET over the existing ``channel.webhook_out`` transport. It emits
the SAME ``channel.webhook_out.queued`` event webhook_out emits, so it rides the
existing SSRF-guarded Rust ``handle_webhook`` with ZERO Rust change. NODE_CHANNEL
maps ``channel.n8n`` -> ChannelType.WEBHOOK (same handler as webhook_out).

Two modes:
  * fire-and-forget (default): POST the lead snapshot to the n8n Webhook node URL
    and continue immediately on ``sent``.
  * wait_for_callback=True: additionally park the lead (mirroring event.invite_accepted)
    and include a signed callback token in the body. n8n calls
    ``POST /n8n/callback/{token}`` to resume this exact lead (``resumed`` handle),
    or the ``timeout`` handle fires after ``callback_timeout_hours``.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, Field, HttpUrl

from app.config import settings
from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)
from app.services.callback_token import make_callback_token


class N8nConfig(BaseModel):
    webhook_url: HttpUrl = Field(description="The n8n Webhook node URL")
    include_lead: bool = Field(True, description="Include the full lead snapshot in the body")
    extra: dict[str, Any] = Field(default_factory=dict, description="Static fields merged into the body")
    wait_for_callback: bool = Field(False, description="Park the lead until n8n calls back")
    callback_timeout_hours: int = Field(24, ge=1, le=720, description="Advance on timeout if no callback arrives")


MANIFEST = NodeManifest(
    type="channel.n8n",
    category=NodeCategory.SINK,
    display_name="n8n workflow",
    summary="Hand this lead to an n8n workflow (and optionally wait for it to call back)",
    config_schema=N8nConfig,
    output_handles=(
        NodeHandle("sent", "Handed off to n8n"),
        NodeHandle("on_error", "n8n endpoint rejected or unreachable"),
        NodeHandle("resumed", "n8n called back (wait_for_callback)"),
        NodeHandle("timeout", "No callback within the timeout window (wait_for_callback)"),
    ),
    side_effect=SideEffect.NETWORK,
    icon="webhook",
    primary_fields=("webhook_url",),
    advanced_fields=("include_lead", "extra", "wait_for_callback", "callback_timeout_hours"),
)


def _lead_snapshot(lead: dict[str, Any]) -> dict[str, Any]:
    """The lead fields we hand to n8n. custom_fields carries the discovered data."""
    return {
        "id": lead.get("id"),
        "contact_id": lead.get("contact_id"),
        "workflow_id": lead.get("workflow_id"),
        "status": lead.get("status"),
        "custom_fields": lead.get("custom_fields") or {},
    }


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = N8nConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())

    body: dict[str, Any] = dict(cfg.extra)
    if cfg.include_lead:
        body["lead"] = _lead_snapshot(ctx.lead)
    body["workspace_id"] = ctx.workspace_id
    body["correlation_id"] = correlation_id

    telemetry: dict[str, Any] = {"correlation_id": correlation_id, "preset": "n8n"}

    if cfg.wait_for_callback and ctx.lead.get("id") and ctx.node_id:
        # Mint a signed callback token so n8n can resume EXACTLY this parked lead.
        token = make_callback_token(
            settings.secret_key,
            workspace_id=str(ctx.workspace_id),
            lead_id=str(ctx.lead["id"]),
            node_id=str(ctx.node_id),
            ttl_seconds=cfg.callback_timeout_hours * 3600,
        )
        body["callback_url"] = f"{settings.get_public_base_url()}/api/n8n/callback/{token}"
        body["callback_token"] = token

    # Emit the SAME intent webhook_out emits — rides the existing Rust handler.
    events = [
        {
            "event_type": "channel.webhook_out.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "url": str(cfg.webhook_url),
                "method": "POST",
                "headers": {},
                "body": body,
                "rendered_template": None,
                "correlation_id": correlation_id,
            },
        }
    ]

    if cfg.wait_for_callback and ctx.lead.get("id") and ctx.node_id:
        # Park the lead: the .queued intent still dispatches the POST (published
        # above), but the lead does NOT advance here — it resumes on the callback
        # (resumed handle) or the timeout. Mirror event.invite_accepted.
        return NodeResult(
            handle="timeout",  # nominal; park=True means the worker won't route on it
            park=True,
            events=events,
            telemetry={
                **telemetry,
                "parked": True,
                "reason": "await_n8n_callback",
                "timeout_seconds": cfg.callback_timeout_hours * 3600,
            },
        )

    return NodeResult(handle="sent", events=events, telemetry=telemetry)


register(MANIFEST, execute)
