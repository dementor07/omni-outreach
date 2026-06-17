"""Human-approval queue (CONTRACT-005).

flow.human_approval parks a lead and emits ``approval.requested`` (projected
into omni_approvals as pending). An operator reviews + resolves it here:

  GET   /approvals             → list pending approvals for the workspace
  PATCH /approvals/{id}/draft  → edit the AI-composed draft before approving (B1)
  POST  /approvals/{id}/resolve → approve/reject

Resolving does two things:
  1. emits ``approval.resolved`` (projector flips the row to the outcome), and
  2. emits a transition on outreach.transitions off the approval's node on the
     chosen handle, which un-parks the lead (the transition worker advances it
     down approved/rejected). This is the resume half of the park/resume pair.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import fetch_all, fetch_one
from app.services import bus
from app.services.bus import publish_event

router = APIRouter()


class ApprovalOut(BaseModel):
    id: uuid.UUID
    lead_id: uuid.UUID
    node_id: uuid.UUID | None
    prompt: str
    draft: str | None
    status: str
    created_at: datetime


class ResolveBody(BaseModel):
    # Maps directly to a human_approval output handle.
    handle: Literal["approved", "rejected"]


class DraftBody(BaseModel):
    draft: str = Field(max_length=20000, description="The reviewed/edited AI draft")


@router.get("", response_model=list[ApprovalOut], summary="List pending approvals")
async def list_approvals(_: AuthContext = Depends(get_current_workspace)) -> list[ApprovalOut]:
    rows = await fetch_all(
        """
        SELECT id, lead_id, node_id, prompt, draft, status, created_at
        FROM omni_approvals
        WHERE status = 'pending'
        ORDER BY created_at ASC
        """
    )
    return [ApprovalOut.model_validate(r) for r in rows]


@router.patch("/{approval_id}/draft", status_code=202, summary="Edit an approval's AI draft (B1)")
async def update_draft(
    approval_id: uuid.UUID,
    body: DraftBody,
    ctx: AuthContext = Depends(get_current_workspace),
) -> dict:
    row = await fetch_one(
        "SELECT id, status, correlation_id FROM omni_approvals WHERE id = $1",
        approval_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="approval not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"approval already {row['status']} — draft is frozen")

    # Event-sourced edit: the projector applies it to the pending row. Mirrors
    # every other state change in v2 (no direct UPDATE from the request path).
    await publish_event(
        workspace_id=ctx.workspace_id,
        event_type="approval.draft_updated",
        entity_type="approval",
        entity_id=str(approval_id),
        payload={"draft": body.draft, "edited_by": ctx.user_id},
        actor_user_id=ctx.user_id,
        correlation_id=str(row["correlation_id"]) if row.get("correlation_id") else None,
    )
    return {"ok": True}


@router.post("/{approval_id}/resolve", status_code=202, summary="Approve or reject a parked lead")
async def resolve_approval(
    approval_id: uuid.UUID,
    body: ResolveBody,
    ctx: AuthContext = Depends(get_current_workspace),
) -> dict:
    row = await fetch_one(
        "SELECT id, lead_id, node_id, status, correlation_id FROM omni_approvals WHERE id = $1",
        approval_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="approval not found")
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"approval already {row['status']}")

    correlation_id = str(row["correlation_id"]) if row.get("correlation_id") else None

    # 1. Projection event: flips the omni_approvals row to the outcome.
    await publish_event(
        workspace_id=ctx.workspace_id,
        event_type="approval.resolved",
        entity_type="approval",
        entity_id=str(approval_id),
        payload={"handle": body.handle, "resolved_by": ctx.user_id},
        actor_user_id=ctx.user_id,
        correlation_id=correlation_id,
    )

    # 2. Resume the lead: emit a transition off the approval's node on the chosen
    #    handle. The transition worker un-parks the lead and advances it.
    transition = {
        "lead_id": str(row["lead_id"]),
        "source_node_id": str(row["node_id"]) if row.get("node_id") else None,
        "handle": body.handle,
        "event_type": "transition",
        "metadata": {
            "workspace_id": ctx.workspace_id,
            "correlation_id": correlation_id,
            "resolved_by": ctx.user_id,
        },
    }
    await bus._producer.send_and_wait(  # type: ignore[union-attr]
        bus.TRANSITIONS_TOPIC, value=transition, key=str(row["lead_id"])
    )

    return {"ok": True, "handle": body.handle}
