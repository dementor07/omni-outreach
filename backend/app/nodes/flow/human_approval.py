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
            "entity_type": "approval",
            "entity_id": ctx.lead.get("id"),
            "payload": {
                "prompt": cfg.prompt,
                "timeout_hours": cfg.timeout_hours,
                "node_id": ctx.node_id,
                "lead_id": ctx.lead.get("id"),
                "correlation_id": correlation_id,
            },
        }
    ]
    # CONTRACT-005: PARK the lead. The old code returned handle="approved",
    # which advanced the lead down the approved edge immediately — it never
    # actually waited for a human. With park=True the transition worker suspends
    # the lead (status='waiting'); it resumes only when the resolve endpoint
    # emits approval.resolved with the operator's chosen handle.
    return NodeResult(
        handle="approved",
        events=events,
        park=True,
        telemetry={"correlation_id": correlation_id, "parked": True},
    )


register(MANIFEST, execute)
