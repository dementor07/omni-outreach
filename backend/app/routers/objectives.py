"""Campaign Objective CRUD — declare the goal a workflow pursues.

A workflow gains at most one objective (metric + target + audience + bounds).
The objective_controller reads it on each run-lead completion and pursues it
(widen + re-run until reached or the bounds envelope is spent). This router is
the operator surface: set/replace the objective, read it (with live progress),
clear it. See ADR campaign-objective-controller.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import execute, fetch_one

router = APIRouter()

# Only metrics the engine can HONESTLY measure from a campaign's own lineage
# (see objective_controller.MEASURABLE_METRICS). meetings_booked is intentionally
# absent — there's no campaign-scoped calendar/deal signal yet, so offering it
# would let an operator set a goal the engine silently scores 0 forever.
Metric = Literal["contacts", "qualified_leads", "companies", "replies"]
Status = Literal["pursuing", "reached", "exhausted", "paused"]


class ObjectiveIn(BaseModel):
    metric: Metric
    target: int = Field(gt=0, le=100_000, description="How many of `metric` to reach")
    audience: dict[str, Any] = Field(
        default_factory=dict,
        description="Sourcing spec — e.g. {keywords:[...], location, titles}. Parameterises the source/screen nodes and the widen ladder.",
    )
    bounds: dict[str, Any] = Field(
        default_factory=dict,
        description="Safety envelope — {max_iterations, max_spend_usd?, deadline?}",
    )


class ObjectiveOut(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    metric: str
    target: int
    audience: dict[str, Any]
    bounds: dict[str, Any]
    progress: dict[str, Any]
    status: str
    created_at: datetime
    updated_at: datetime


@router.get(
    "/{workflow_id}",
    response_model=ObjectiveOut | None,
    summary="Get a workflow's objective (with live progress), or null if none",
)
async def get_objective(
    workflow_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)
) -> ObjectiveOut | None:
    row = await fetch_one(
        "SELECT * FROM omni_campaign_objectives WHERE workflow_id = $1", workflow_id
    )
    return ObjectiveOut.model_validate(row) if row else None


@router.put(
    "/{workflow_id}",
    response_model=ObjectiveOut,
    summary="Declare or replace a workflow's objective (resets pursuit)",
)
async def set_objective(
    workflow_id: uuid.UUID,
    body: ObjectiveIn,
    ctx: AuthContext = Depends(get_current_workspace),
) -> ObjectiveOut:
    wf = await fetch_one(
        "SELECT id FROM omni_workflows WHERE id = $1 AND workspace_id = $2",
        workflow_id, ctx.workspace_id,
    )
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")

    # Upsert on (workspace, workflow): one objective per campaign. Declaring/
    # replacing resets pursuit — fresh progress + status='pursuing'.
    row = await fetch_one(
        """
        INSERT INTO omni_campaign_objectives
            (workspace_id, workflow_id, metric, target, audience, bounds, progress, status)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6::jsonb, '{}'::jsonb, 'pursuing')
        ON CONFLICT (workspace_id, workflow_id) DO UPDATE SET
            metric    = EXCLUDED.metric,
            target    = EXCLUDED.target,
            audience  = EXCLUDED.audience,
            bounds    = EXCLUDED.bounds,
            progress  = '{}'::jsonb,
            status    = 'pursuing',
            updated_at = NOW()
        RETURNING *
        """,
        ctx.workspace_id,
        workflow_id,
        body.metric,
        body.target,
        json.dumps(body.audience),
        json.dumps(body.bounds),
    )
    return ObjectiveOut.model_validate(row)


@router.delete(
    "/{workflow_id}",
    status_code=204,
    summary="Clear a workflow's objective (stops pursuit)",
)
async def clear_objective(
    workflow_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)
) -> None:
    await execute(
        "DELETE FROM omni_campaign_objectives WHERE workflow_id = $1", workflow_id
    )


@router.post(
    "/{workflow_id}/pause",
    response_model=ObjectiveOut,
    summary="Pause/resume pursuit (recourse — steer mid-flight)",
)
async def toggle_pause(
    workflow_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)
) -> ObjectiveOut:
    row = await fetch_one(
        "SELECT status FROM omni_campaign_objectives WHERE workflow_id = $1", workflow_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="objective not found")
    # paused <-> pursuing toggle; terminal states (reached/exhausted) are not toggled.
    if row["status"] not in ("pursuing", "paused"):
        raise HTTPException(status_code=409, detail=f"objective is {row['status']}, cannot pause/resume")
    new_status = "paused" if row["status"] == "pursuing" else "pursuing"
    updated = await fetch_one(
        "UPDATE omni_campaign_objectives SET status = $1, updated_at = NOW() "
        "WHERE workflow_id = $2 RETURNING *",
        new_status, workflow_id,
    )
    return ObjectiveOut.model_validate(updated)
