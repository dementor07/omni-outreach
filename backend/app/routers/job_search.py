import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import fetch_all, fetch_one
from app.services.job_search import run_job_search

router = APIRouter()

_CONFIG_COLS = """
    id, campaign_id,
    job_keywords AS keywords,
    job_location AS location,
    serper_roles AS roles,
    is_enabled AS is_active,
    created_at
"""

_RUN_COLS = """
    id, campaign_id, config_id,
    CASE WHEN status = 'done' THEN 'completed' ELSE status END AS status,
    leads_found,
    started_at,
    finished_at AS completed_at,
    error AS error_message
"""


class TriggerRequest(BaseModel):
    campaign_id: str
    config_id: str


class ConfigCreate(BaseModel):
    campaign_id: str
    keywords: list[str]
    location: str
    roles: list[str]


@router.post("/trigger")
async def trigger_job_search(
    body: TriggerRequest,
    user_id: str = Depends(get_current_user),
):
    asyncio.create_task(run_job_search(body.campaign_id, body.config_id))
    return {"status": "started", "campaign_id": body.campaign_id}


@router.post("/configs", status_code=201)
async def create_config(body: ConfigCreate, user_id: str = Depends(get_current_user)):
    campaign = await fetch_one("SELECT id FROM campaigns WHERE id=$1", body.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    row = await fetch_one(
        f"""
        INSERT INTO job_search_configs (campaign_id, job_keywords, job_location, serper_roles)
        VALUES ($1, $2, $3, $4)
        RETURNING {_CONFIG_COLS}
        """,
        body.campaign_id, body.keywords, body.location, body.roles,
    )
    return row


@router.get("/runs")
async def list_runs(
    campaign_id: str | None = None,
    config_id: str | None = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user),
):
    conditions: list[str] = []
    params: list = []

    if campaign_id:
        params.append(campaign_id)
        conditions.append(f"campaign_id=${len(params)}")
    if config_id:
        params.append(config_id)
        conditions.append(f"config_id=${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = await fetch_all(
        f"SELECT {_RUN_COLS} FROM job_search_runs {where} ORDER BY started_at DESC LIMIT ${len(params)}",
        *params,
    )
    return rows


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user_id: str = Depends(get_current_user)):
    row = await fetch_one(
        f"SELECT {_RUN_COLS} FROM job_search_runs WHERE id=$1", run_id
    )
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row


@router.get("/configs/{campaign_id}")
async def list_configs(campaign_id: str, user_id: str = Depends(get_current_user)):
    rows = await fetch_all(
        f"SELECT {_CONFIG_COLS} FROM job_search_configs WHERE campaign_id=$1",
        campaign_id,
    )
    return rows
