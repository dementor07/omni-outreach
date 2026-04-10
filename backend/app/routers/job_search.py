from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from app.auth import get_current_user
from app.db import fetch_all, fetch_one
from app.services.job_search import run_job_search
import asyncio

router = APIRouter()


class TriggerRequest(BaseModel):
    campaign_id: str
    config_id: str


@router.post("/trigger")
async def trigger_job_search(
    body: TriggerRequest,
    user_id: str = Depends(get_current_user),
):
    asyncio.create_task(run_job_search(body.campaign_id, body.config_id))
    return {"status": "started", "campaign_id": body.campaign_id}


@router.get("/runs")
async def list_runs(
    campaign_id: str | None = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user),
):
    if campaign_id:
        rows = await fetch_all(
            "SELECT * FROM job_search_runs WHERE campaign_id=$1 ORDER BY started_at DESC LIMIT $2",
            campaign_id, limit,
        )
    else:
        rows = await fetch_all(
            "SELECT * FROM job_search_runs ORDER BY started_at DESC LIMIT $1", limit
        )
    return {"runs": rows}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user_id: str = Depends(get_current_user)):
    row = await fetch_one("SELECT * FROM job_search_runs WHERE id=$1", run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.get("/configs/{campaign_id}")
async def list_configs(campaign_id: str, user_id: str = Depends(get_current_user)):
    rows = await fetch_all(
        "SELECT * FROM job_search_configs WHERE campaign_id=$1", campaign_id
    )
    return {"configs": rows}
