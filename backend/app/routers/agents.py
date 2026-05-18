"""Read-only endpoints to surface agent run state to the operator UI.

The agent runtime itself lives in app.services.agent. This module only exposes
the JSON shape the frontend trace panel consumes.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth import get_current_user
from app.db import fetch_all, fetch_one
from app.services.agent_tools import registry as tool_registry

router = APIRouter()
log = logging.getLogger(__name__)


@router.get("/tools")
async def list_tools(_user_id: str = Depends(get_current_user)):
    """Returns the names + descriptions of every registered agent tool.

    The canvas ConfigSidebar uses this to render the tool checklist for an
    action_agent node.
    """
    return {"tools": tool_registry.list_specs()}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, _user_id: str = Depends(get_current_user)):
    row = await fetch_one("SELECT * FROM agent_runs WHERE id=$1", run_id)
    if not row:
        raise HTTPException(status_code=404, detail="agent run not found")
    return row


@router.get("/runs")
async def list_runs(
    lead_id: str | None = None,
    campaign_id: str | None = None,
    limit: int = 25,
    _user_id: str = Depends(get_current_user),
):
    limit = max(1, min(200, int(limit)))
    where = []
    args: list = []
    if lead_id:
        args.append(lead_id)
        where.append(f"lead_id = ${len(args)}")
    if campaign_id:
        args.append(campaign_id)
        where.append(f"campaign_id = ${len(args)}")
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    args.append(limit)
    rows = await fetch_all(
        f"SELECT id, lead_id, campaign_id, node_id, status, outcome, turns_used, "
        f"tokens_used, started_at, finished_at FROM agent_runs{clause} "
        f"ORDER BY started_at DESC LIMIT ${len(args)}",
        *args,
    )
    return {"runs": rows}
