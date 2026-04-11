from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

router = APIRouter()


class CampaignCreate(BaseModel):
    name: str
    daily_lead_cap: int = 50
    invite_daily_cap: int = 20
    simulation_mode: bool = False
    timezone: str = "Asia/Kolkata"
    active_hours_start: int = 9
    active_hours_end: int = 18
    screening_prompt: str | None = None
    sequence_mode: str = "sequential"


class CampaignUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    daily_lead_cap: int | None = None
    invite_daily_cap: int | None = None
    simulation_mode: bool | None = None
    timezone: str | None = None
    active_hours_start: int | None = None
    active_hours_end: int | None = None
    screening_prompt: str | None = None
    sequence_mode: str | None = None


@router.get("")
async def list_campaigns(user_id: str = Depends(get_current_user)):
    return await fetch_all("SELECT * FROM campaigns ORDER BY created_at DESC")


@router.post("", status_code=201)
async def create_campaign(body: CampaignCreate, user_id: str = Depends(get_current_user)):
    return await fetch_one(
        """
        INSERT INTO campaigns
            (name, daily_lead_cap, invite_daily_cap, simulation_mode,
             timezone, active_hours_start, active_hours_end, screening_prompt, sequence_mode)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        RETURNING *
        """,
        body.name, body.daily_lead_cap, body.invite_daily_cap, body.simulation_mode,
        body.timezone, body.active_hours_start, body.active_hours_end, body.screening_prompt,
        body.sequence_mode,
    )


@router.get("/{campaign_id}")
async def get_campaign(campaign_id: str, user_id: str = Depends(get_current_user)):
    row = await fetch_one("SELECT * FROM campaigns WHERE id=$1", campaign_id)
    if not row:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return row


@router.put("/{campaign_id}")
async def update_campaign(
    campaign_id: str, body: CampaignUpdate, user_id: str = Depends(get_current_user)
):
    existing = await fetch_one("SELECT id FROM campaigns WHERE id=$1", campaign_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Campaign not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    set_clause = ", ".join(f"{k}=${i+2}" for i, k in enumerate(updates))
    values = list(updates.values())
    return await fetch_one(
        f"UPDATE campaigns SET {set_clause} WHERE id=$1 RETURNING *",
        campaign_id, *values,
    )


@router.delete("/{campaign_id}", status_code=204)
async def delete_campaign(campaign_id: str, user_id: str = Depends(get_current_user)):
    await execute("UPDATE campaigns SET status='archived' WHERE id=$1", campaign_id)


@router.get("/{campaign_id}/stats")
async def campaign_stats(campaign_id: str, user_id: str = Depends(get_current_user)):
    return await fetch_one(
        """
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE status='active') AS active,
            COUNT(*) FILTER (WHERE invited_at IS NOT NULL) AS invited,
            COUNT(*) FILTER (WHERE accepted_at IS NOT NULL) AS accepted,
            COUNT(*) FILTER (WHERE status='stopped') AS stopped
        FROM leads WHERE campaign_id=$1
        """,
        campaign_id,
    )
