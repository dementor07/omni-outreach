"""
Lead generation API router.
Supersedes /job-search/ with a multi-source provider model.
"""
from __future__ import annotations

import asyncio

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one
from app.services.lead_gen import run_lead_gen
from app.services.lead_source_registry import registry

router = APIRouter()

# ── Sources ───────────────────────────────────────────────────────────────────

@router.get("/sources")
async def list_sources(user_id: str = Depends(get_current_user)):
    """Return all registered lead sources with availability status."""
    return [s.describe() for s in registry.all()]


# ── Configs ───────────────────────────────────────────────────────────────────

class ConfigCreate(BaseModel):
    campaign_id: str
    source_type: str
    config: dict = {}
    label: str | None = None  # optional human label for the config card


_CONFIG_COLS = "id, campaign_id, source_type, config, label, is_enabled, cron_schedule, last_run_at, created_at"


@router.post("/configs", status_code=201)
async def create_config(body: ConfigCreate, user_id: str = Depends(get_current_user)):
    campaign = await fetch_one("SELECT id FROM campaigns WHERE id=$1", body.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    source = registry.get(body.source_type)
    if not source:
        raise HTTPException(status_code=400, detail=f"Unknown source_type: {body.source_type}")

    row = await fetch_one(
        f"""
        INSERT INTO lead_gen_configs (campaign_id, source_type, config, label)
        VALUES ($1, $2, $3, $4)
        RETURNING {_CONFIG_COLS}
        """,
        body.campaign_id,
        body.source_type,
        body.config,
        body.label,
    )
    return row


@router.get("/configs/{campaign_id}")
async def list_configs(campaign_id: str, user_id: str = Depends(get_current_user)):
    rows = await fetch_all(
        f"SELECT {_CONFIG_COLS} FROM lead_gen_configs WHERE campaign_id=$1 ORDER BY created_at DESC",
        campaign_id,
    )
    # Annotate each config with source availability
    result = []
    for row in rows:
        d = dict(row)
        source = registry.get(d["source_type"])
        d["source_available"] = source.is_available if source else False
        d["source_display_name"] = source.display_name if source else d["source_type"]
        result.append(d)
    return result


@router.delete("/configs/{config_id}", status_code=204)
async def delete_config(config_id: str, user_id: str = Depends(get_current_user)):
    await execute("DELETE FROM lead_gen_configs WHERE id=$1", config_id)


class ConfigUpdate(BaseModel):
    cron_schedule: str | None = None
    is_enabled: bool | None = None
    config: dict | None = None
    label: str | None = None


@router.patch("/configs/{config_id}")
async def update_config(
    config_id: str,
    body: ConfigUpdate,
    user_id: str = Depends(get_current_user),
):
    existing = await fetch_one("SELECT id FROM lead_gen_configs WHERE id=$1", config_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Config not found")

    # Validate cron expression if provided (non-null, non-empty)
    if body.cron_schedule:
        try:
            from croniter import croniter
            if not croniter.is_valid(body.cron_schedule):
                raise ValueError("invalid cron expression")
        except ImportError:
            pass  # croniter not installed yet — skip validation in that environment

    sets: list[str] = []
    params: list = []
    for col, val in [
        ("cron_schedule", body.cron_schedule),
        ("is_enabled", body.is_enabled),
        ("config", body.config),
        ("label", body.label),
    ]:
        if val is not None:
            params.append(val)
            sets.append(f"{col}=${len(params)}")

    # Allow clearing cron_schedule explicitly by sending empty string
    if body.cron_schedule == "":
        sets.append("cron_schedule=NULL")

    if not sets:
        existing_full = await fetch_one(
            f"SELECT {_CONFIG_COLS} FROM lead_gen_configs WHERE id=$1", config_id
        )
        return existing_full

    params.append(config_id)
    row = await fetch_one(
        f"UPDATE lead_gen_configs SET {', '.join(sets)} WHERE id=${len(params)} RETURNING {_CONFIG_COLS}",
        *params,
    )
    return row


# ── Runs ──────────────────────────────────────────────────────────────────────

_RUN_COLS = "id, campaign_id, config_id, source_type, status, leads_found, leads_added, started_at, finished_at, error, triggered_by"


class TriggerRequest(BaseModel):
    campaign_id: str
    config_id: str


@router.post("/trigger")
async def trigger_run(body: TriggerRequest, user_id: str = Depends(get_current_user)):
    config = await fetch_one("SELECT * FROM lead_gen_configs WHERE id=$1", body.config_id)
    if not config:
        raise HTTPException(status_code=404, detail="Config not found")

    source = registry.get(config["source_type"])
    if not source:
        raise HTTPException(status_code=400, detail=f"Unknown source: {config['source_type']}")
    if not source.is_available:
        raise HTTPException(
            status_code=422,
            detail=f"Source '{source.display_name}' is not configured. Add the API key in Settings.",
        )

    asyncio.create_task(run_lead_gen(body.campaign_id, body.config_id))
    return {"status": "started", "source_type": config["source_type"]}


@router.get("/runs")
async def list_runs(
    campaign_id: str | None = None,
    config_id: str | None = None,
    source_type: str | None = None,
    limit: int = 20,
    user_id: str = Depends(get_current_user),
):
    conditions: list[str] = []
    params: list = []

    for col, val in [("campaign_id", campaign_id), ("config_id", config_id), ("source_type", source_type)]:
        if val is not None:
            params.append(val)
            conditions.append(f"{col}=${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = await fetch_all(
        f"SELECT {_RUN_COLS} FROM lead_gen_runs {where} ORDER BY started_at DESC LIMIT ${len(params)}",
        *params,
    )
    return rows


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user_id: str = Depends(get_current_user)):
    row = await fetch_one(f"SELECT {_RUN_COLS} FROM lead_gen_runs WHERE id=$1", run_id)
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    return row
