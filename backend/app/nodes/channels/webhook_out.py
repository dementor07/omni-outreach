"""Outbound webhook — POST/PUT/PATCH to an arbitrary operator-supplied URL.

SSRF-guarded: the Rust muscle's ``handle_webhook`` rejects loopback,
RFC-1918, link-local, and cloud-metadata hosts. This Python shim only
validates the config and queues the command.
"""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field, HttpUrl

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)


class WebhookOutConfig(BaseModel):
    url: HttpUrl = Field(description="Destination URL (http/https; private IPs blocked)")
    method: Literal["POST", "PUT", "PATCH", "DELETE"] = Field("POST")
    headers: dict[str, str] = Field(default_factory=dict, description="Extra HTTP headers")
    body: dict[str, Any] | None = Field(None, description="JSON body; if null, a default lead snapshot is sent")
    rendered_template: str | None = Field(None, description="Pre-rendered body string (overrides 'body')")


MANIFEST = NodeManifest(
    type="channel.webhook_out",
    category=NodeCategory.SINK,
    summary="POST/PUT/PATCH/DELETE to an arbitrary URL (CRM handoff, Zapier, …)",
    config_schema=WebhookOutConfig,
    output_handles=(
        NodeHandle("sent", "Target responded 2xx"),
        NodeHandle("on_error", "Target rejected or unreachable"),
    ),
    side_effect=SideEffect.NETWORK,
    icon="webhook",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = WebhookOutConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "channel.webhook_out.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "url": str(cfg.url),
                "method": cfg.method,
                "headers": cfg.headers,
                "body": cfg.body,
                "rendered_template": cfg.rendered_template,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="sent", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
