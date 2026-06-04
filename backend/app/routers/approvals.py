"""Human-approval queue (CONTRACT-005).

flow.human_approval parks a lead and emits ``approval.requested`` (projected
into omni_approvals as pending). An operator resolves it here:

  GET  /approvals          → list pending approvals for the workspace
  POST /approvals/{id}/resolve  → approve/reject

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
from pydantic import BaseModel

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
    status: str
    created_at: datetime


class ResolveBody(BaseModel):
    # Maps directly to a human_approval output handle.
    handle: Literal["approved", "rejected"]


@router.get("", response_model=list[ApprovalOut], summary="List pending approvals")
async def list_approvals(_: AuthContext = Depends(get_current_workspace)) -> list[ApprovalOut]:
    rows = await fetch_all(
        """
        SELECT id, lead_id, node_id, prompt, status, created_at
        FROM omni_approvals
        WHERE status = 'pending'
        ORDER BY created_at ASC
        """
    )
    return [ApprovalOut.model_validate(r) for r in rows]


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
