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
    draft_variable: str = Field(
        "ai_draft",
        description="Lead variable holding an AI-composed draft to review (e.g. ai.compose's target_variable)",
    )


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


_APPROVAL_NS = uuid.UUID("a99a0f1e-6b2d-4c3a-9e4f-2c1b0a9d8e7f")


def _lead_draft(lead: dict, variable: str) -> str | None:
    """Pull an upstream AI-composed draft off the lead's custom_fields (B1).

    ai.compose writes its draft into the lead context under its target_variable
    (default 'ai_draft'). When that variable is present, the approval carries it
    so the operator reviews + edits the AI copy before it advances."""
    cf = lead.get("custom_fields") or {}
    if isinstance(cf, str):
        import json

        try:
            cf = json.loads(cf)
        except Exception:  # noqa: BLE001
            return None
    value = cf.get(variable)
    return str(value) if value not in (None, "") else None


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = HumanApprovalConfig(**ctx.config)
    correlation_id = ctx.correlation_id or str(uuid.uuid4())
    draft = _lead_draft(ctx.lead, cfg.draft_variable)
    # APPROVAL-ID-001: the approval id must be unique per (lead, NODE), not per
    # lead. Keyed on lead_id alone, a sequence with more than one human_approval
    # step reuses the same id — the projector's INSERT … ON CONFLICT (id) DO
    # NOTHING then drops every approval after the first, and the lead parks
    # forever with no queue row. uuid5(lead:node) is unique per step yet stable,
    # so a redelivery of the SAME step still collapses (idempotent).
    lead_id = ctx.lead.get("id")
    approval_id = str(uuid.uuid5(_APPROVAL_NS, f"{lead_id}:{ctx.node_id}"))
    events = [
        {
            "event_type": "approval.requested",
            "entity_type": "approval",
            "entity_id": approval_id,
            "payload": {
                "prompt": cfg.prompt,
                "draft": draft,
                "timeout_hours": cfg.timeout_hours,
                "node_id": ctx.node_id,
                "lead_id": lead_id,
                "correlation_id": correlation_id,
            },
        }
    ]
    # CONTRACT-005: PARK the lead. The old code returned handle="approved",
    # which advanced the lead down the approved edge immediately — it never
    # actually waited for a human. With park=True the transition worker suspends
    # the lead (status='waiting'); it resumes only when the resolve endpoint
    # emits approval.resolved with the operator's chosen handle.
    # timeout_seconds arms the transition worker's park-timeout escape (the same
    # mechanism event.* nodes use): if no operator resolves the approval within
    # timeout_hours, a delayed 'timeout' transition fires so the lead auto-rejects
    # instead of stranding 'waiting' forever. Without this the timeout_hours field
    # was decorative — an un-actioned approval never resolved.
    return NodeResult(
        handle="approved",
        events=events,
        park=True,
        telemetry={
            "correlation_id": correlation_id,
            "parked": True,
            "timeout_seconds": float(cfg.timeout_hours) * 3600.0,
        },
    )


register(MANIFEST, execute)
