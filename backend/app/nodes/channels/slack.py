"""Slack alert channel — internal team notifications, not contact-facing."""

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


class SlackAlertConfig(BaseModel):
    connection_name: str = Field(description="Slack incoming-webhook connection (Settings → Integrations)")
    title_template: str = Field(min_length=1, max_length=200, description="Bold heading; supports {{contact.first_name}} variables")
    body_template: str = Field(min_length=1, max_length=4000, description="Message body; supports variables")


MANIFEST = NodeManifest(
    type="channel.slack",
    category=NodeCategory.CHANNEL,
    summary="Post an alert to a Slack channel (operator-facing, not contact-facing)",
    config_schema=SlackAlertConfig,
    output_handles=(
        NodeHandle("sent", "Slack accepted the webhook"),
        NodeHandle("on_error", "Webhook URL invalid or revoked"),
    ),
    capabilities=("connection:slack",),
    side_effect=SideEffect.NETWORK,
    icon="slack",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = SlackAlertConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "channel.slack.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "connection_name": cfg.connection_name,
                "title_template": cfg.title_template,
                "body_template": cfg.body_template,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="sent", events=events, telemetry={"correlation_id": correlation_id})


register(MANIFEST, execute)
