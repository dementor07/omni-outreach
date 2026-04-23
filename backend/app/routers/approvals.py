"""Human approvals router — inbox for `human_approval` nodes.

`human_approval` nodes park a lead and open a row here. The user reviews and
either approves (lead advances on handle 'approve') or rejects (handle 'reject').
"""
from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one
from app.services import sequencer

router = APIRouter()
log = logging.getLogger(__name__)


_COLS = (
    "a.id, a.campaign_id, a.lead_id, a.node_id, a.title, a.payload, a.status, "
    "a.resolution, a.resolved_by, a.resolved_at, a.created_at, "
    "l.first_name, l.last_name, l.email, l.linkedin_url, l.headline, l.company, "
    "c.name AS campaign_name"
)


@router.get("")
async def list_approvals(
    status: str = "pending",
    campaign_id: str | None = None,
    limit: int = 50,
    user_id: str = Depends(get_current_user),
):
    conditions = ["a.status = $1"]
    params: list = [status]
    if campaign_id:
        params.append(campaign_id)
        conditions.append(f"a.campaign_id = ${len(params)}")
    params.append(limit)
    rows = await fetch_all(
        f"""
        SELECT {_COLS}
        FROM approvals a
        JOIN leads l ON l.id = a.lead_id
        JOIN campaigns c ON c.id = a.campaign_id
        WHERE {' AND '.join(conditions)}
        ORDER BY a.created_at DESC
        LIMIT ${len(params)}
        """,
        *params,
    )
    return rows


@router.get("/count")
async def approvals_count(user_id: str = Depends(get_current_user)):
    row = await fetch_one(
        "SELECT COUNT(*) AS pending FROM approvals WHERE status = 'pending'"
    )
    return {"pending": (row or {}).get("pending", 0)}


class ResolveRequest(BaseModel):
    resolution: Literal["approve", "reject"]
    note: str | None = None


@router.post("/{approval_id}/resolve")
async def resolve_approval(
    approval_id: str,
    body: ResolveRequest,
    user_id: str = Depends(get_current_user),
):
    approval = await fetch_one(
        "SELECT id, lead_id, status FROM approvals WHERE id=$1",
        approval_id,
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    if approval["status"] != "pending":
        raise HTTPException(status_code=409, detail=f"Approval already {approval['status']}")

    new_status = "approved" if body.resolution == "approve" else "rejected"
    await execute(
        """
        UPDATE approvals
        SET status=$2, resolution=$3, resolved_by=$4, resolved_at=NOW()
        WHERE id=$1
        """,
        approval_id, new_status, body.note, user_id,
    )
    log.info(f"[approvals] {approval_id} resolved: {new_status} by {user_id}")
    await sequencer.resume_from_approval(
        str(approval["lead_id"]), approval_id, body.resolution,
    )
    return {"status": new_status}
