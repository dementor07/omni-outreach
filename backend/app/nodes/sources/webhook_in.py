"""Inbound webhook source — exposes a stable URL that creates a contact per POST.

The HTTP listener lives at ``POST /webhooks/in/{workflow_id}/{node_id}``
(app/routers/webhooks_in.py). This node is the canvas-side declaration:
operators configure the expected payload shape (field_map + HMAC), and the
webhook handler maps each inbound POST to a contact, seeds a lead at this node,
and advances it down the workflow.
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


class WebhookInConfig(BaseModel):
    require_hmac: bool = Field(True, description="Verify x-omni-signature HMAC header against the workflow secret")
    field_map: dict[str, str] = Field(
        default_factory=dict,
        description="Map incoming JSON paths to contact fields (e.g. {\"email\": \"data.user.email\"})",
    )


MANIFEST = NodeManifest(
    type="source.webhook_in",
    category=NodeCategory.SOURCE,
    summary="Receive contacts from an external system via a workspace-scoped inbound URL",
    config_schema=WebhookInConfig,
    output_handles=(NodeHandle("default", "Emitted on each accepted inbound POST"),),
    side_effect=SideEffect.READ,
    icon="webhook",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = WebhookInConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "source.webhook_in.registered",
            "entity_type": "workflow",
            "entity_id": ctx.workflow_id,
            "payload": {
                "node_id": ctx.node_id,
                "require_hmac": cfg.require_hmac,
                "field_map": cfg.field_map,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
