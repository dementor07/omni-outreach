"""Notify the team that the current lead is hot (Slack / email digest).

Emits a high-priority alert event the muscle routes to the configured channel.
"""

from __future__ import annotations

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


class HotLeadAlertConfig(BaseModel):
    connection_name: str | None = Field(None, description="Slack connection to notify; falls back to the workspace default")
    note_template: str = Field(
        "🔥 Hot lead: {{contact.first_name}} {{contact.last_name}} ({{contact.company}})",
        min_length=1,
        max_length=500,
        description="Alert message; supports {{contact.*}} variables",
    )


MANIFEST = NodeManifest(
    type="crm.hot_lead_alert",
    category=NodeCategory.CRM,
    summary="Send a hot-lead alert to the team",
    config_schema=HotLeadAlertConfig,
    output_handles=(
        NodeHandle("default", "Alert dispatched"),
        NodeHandle("on_error", "Alert could not be delivered"),
    ),
    capabilities=("connection:slack",),
    side_effect=SideEffect.NETWORK,
    icon="flame",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = HotLeadAlertConfig(**ctx.config)
    # CONTRACT-002: the dispatcher only routes intent events (suffix
    # .queued/.requested). The old 'lead.hot_alert' failed _is_intent, so the
    # HOT_LEAD_ALERT muscle channel (which has a real Rust handler) was never
    # reached and no alert was ever sent. Emit the .queued intent so node_type
    # routing fires.
    events = [
        {
            "event_type": "crm.hot_lead_alert.queued",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {"connection_name": cfg.connection_name, "note_template": cfg.note_template},
        }
    ]
    return NodeResult(handle="default", events=events, telemetry={"connection_name": cfg.connection_name})


register(MANIFEST, execute)
