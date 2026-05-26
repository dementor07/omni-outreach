"""Park the lead until an operator approves or rejects it.

Surfaces in the Approvals queue. When the operator clicks Approve/Reject,
an ``approval.resolved`` event fires with the chosen handle.
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


class HumanApprovalConfig(BaseModel):
    prompt: str = Field(min_length=1, max_length=500, description="What the operator sees in the approvals queue")
    timeout_hours: int = Field(48, ge=1, le=720, description="Auto-reject after this window")


MANIFEST = NodeManifest(
    type="flow.human_approval",
    category=NodeCategory.FLOW,
    summary="Pause the lead until an operator approves or rejects it",
    config_schema=HumanApprovalConfig,
    output_handles=(
        NodeHandle("approved", "Operator clicked Approve"),
        NodeHandle("rejected", "Operator clicked Reject"),
        NodeHandle("timeout", "Auto-rejected after the configured window"),
    ),
    side_effect=SideEffect.MUTATE,
    icon="hand",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = HumanApprovalConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    events = [
        {
            "event_type": "approval.requested",
            "entity_type": "lead",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "prompt": cfg.prompt,
                "timeout_hours": cfg.timeout_hours,
                "node_id": ctx.node_id,
                "correlation_id": correlation_id,
            },
        }
    ]
    return NodeResult(handle="approved", events=events, telemetry={"correlation_id": correlation_id, "parked": True})


register(MANIFEST, execute)
