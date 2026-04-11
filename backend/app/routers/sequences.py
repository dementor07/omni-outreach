from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

router = APIRouter()

ChannelType = Literal["linkedin_invite", "linkedin_dm", "email", "voice"]


class StepCreate(BaseModel):
    campaign_id: str
    step_order: int
    channel: ChannelType
    delay_days: int = 0
    voice_agent_id: str | None = None
    email_account_id: str | None = None
    template_id: str | None = None


class StepUpdate(BaseModel):
    step_order: int | None = None
    channel: ChannelType | None = None
    delay_days: int | None = None
    voice_agent_id: str | None = None
    email_account_id: str | None = None
    template_id: str | None = None


@router.get("")
async def list_steps(campaign_id: str, user_id: str = Depends(get_current_user)):
    return await fetch_all(
        """
        SELECT ss.*,
               va.name      AS voice_agent_name,
               ea.from_email AS email_account_email
        FROM sequence_steps ss
        LEFT JOIN voice_agents   va ON va.id = ss.voice_agent_id
        LEFT JOIN email_accounts ea ON ea.id = ss.email_account_id
        WHERE ss.campaign_id = $1
        ORDER BY ss.step_order ASC
        """,
        campaign_id,
    )


@router.post("", status_code=201)
async def create_step(body: StepCreate, user_id: str = Depends(get_current_user)):
    campaign = await fetch_one("SELECT id FROM campaigns WHERE id=$1", body.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    existing = await fetch_one(
        "SELECT id FROM sequence_steps WHERE campaign_id=$1 AND step_order=$2",
        body.campaign_id, body.step_order,
    )
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"A step with order {body.step_order} already exists for this campaign",
        )

    return await fetch_one(
        """
        INSERT INTO sequence_steps
            (campaign_id, step_order, channel, delay_days, voice_agent_id, email_account_id, template_id)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING *
        """,
        body.campaign_id, body.step_order, body.channel, body.delay_days,
        body.voice_agent_id, body.email_account_id, body.template_id,
    )


@router.put("/{step_id}")
async def update_step(
    step_id: str, body: StepUpdate, user_id: str = Depends(get_current_user)
):
    step = await fetch_one("SELECT * FROM sequence_steps WHERE id=$1", step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    updates = body.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    if "step_order" in updates:
        conflict = await fetch_one(
            "SELECT id FROM sequence_steps WHERE campaign_id=$1 AND step_order=$2 AND id<>$3",
            step["campaign_id"], updates["step_order"], step_id,
        )
        if conflict:
            raise HTTPException(
                status_code=409,
                detail=f"A step with order {updates['step_order']} already exists",
            )

    set_clause = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(updates))
    values = list(updates.values())
    return await fetch_one(
        f"UPDATE sequence_steps SET {set_clause} WHERE id=$1 RETURNING *",
        step_id, *values,
    )


@router.delete("/{step_id}", status_code=204)
async def delete_step(step_id: str, user_id: str = Depends(get_current_user)):
    step = await fetch_one("SELECT id FROM sequence_steps WHERE id=$1", step_id)
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    await execute("DELETE FROM sequence_steps WHERE id=$1", step_id)
