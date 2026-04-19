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
    active_days: list[int] = [1, 2, 3, 4, 5, 6]  # Mon=1 to Sun=7
    screening_prompt: str | None = None
    sequence_mode: str = "sequential"
    scheduled_start: str | None = None  # ISO datetime to auto-start
    scheduled_pause: str | None = None  # ISO datetime to auto-pause


class CampaignUpdate(BaseModel):
    name: str | None = None
    status: str | None = None
    daily_lead_cap: int | None = None
    invite_daily_cap: int | None = None
    simulation_mode: bool | None = None
    timezone: str | None = None
    active_hours_start: int | None = None
    active_hours_end: int | None = None
    active_days: list[int] | None = None
    screening_prompt: str | None = None
    sequence_mode: str | None = None
    scheduled_start: str | None = None
    scheduled_pause: str | None = None


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


@router.post("/{campaign_id}/clone", status_code=201)
async def clone_campaign(campaign_id: str, user_id: str = Depends(get_current_user)):
    """Deep-clone a campaign: settings + full sequence graph (nodes + edges)."""
    src = await fetch_one("SELECT * FROM campaigns WHERE id=$1", campaign_id)
    if not src:
        raise HTTPException(404, "Campaign not found")

    # Clone campaign row
    new_campaign = await fetch_one(
        """
        INSERT INTO campaigns
            (name, daily_lead_cap, invite_daily_cap, simulation_mode,
             timezone, active_hours_start, active_hours_end, screening_prompt, sequence_mode)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
        RETURNING *
        """,
        f"{src['name']} (Copy)", src["daily_lead_cap"], src["invite_daily_cap"],
        src["simulation_mode"], src["timezone"], src["active_hours_start"],
        src["active_hours_end"], src.get("screening_prompt"), src.get("sequence_mode", "sequential"),
    )
    new_id = new_campaign["id"]

    # Clone sequence nodes + build old→new ID map
    old_nodes = await fetch_all(
        "SELECT * FROM sequence_nodes WHERE campaign_id=$1", campaign_id
    )
    id_map: dict[str, str] = {}
    for n in old_nodes:
        new_node = await fetch_one(
            """
            INSERT INTO sequence_nodes (campaign_id, node_type, position_x, position_y, data)
            VALUES ($1,$2,$3,$4,$5) RETURNING id
            """,
            new_id, n["node_type"], n["position_x"], n["position_y"], n.get("data"),
        )
        id_map[str(n["id"])] = str(new_node["id"])

    # Clone edges using mapped IDs
    old_edges = await fetch_all(
        "SELECT * FROM sequence_edges WHERE campaign_id=$1", campaign_id
    )
    for e in old_edges:
        src_mapped = id_map.get(str(e["source_node_id"]))
        tgt_mapped = id_map.get(str(e["target_node_id"]))
        if src_mapped and tgt_mapped:
            await execute(
                """
                INSERT INTO sequence_edges (campaign_id, source_node_id, target_node_id, source_handle, target_handle)
                VALUES ($1,$2,$3,$4,$5)
                """,
                new_id, src_mapped, tgt_mapped,
                e.get("source_handle", "default"), e.get("target_handle", "default"),
            )

    # Clone account assignments
    await execute(
        """
        INSERT INTO campaign_linkedin_accounts (campaign_id, account_id)
        SELECT $1, account_id FROM campaign_linkedin_accounts WHERE campaign_id=$2
        ON CONFLICT DO NOTHING
        """,
        new_id, campaign_id,
    )

    return new_campaign


class AccountAssign(BaseModel):
    account_id: str


@router.get("/{campaign_id}/accounts")
async def list_campaign_accounts(campaign_id: str, user_id: str = Depends(get_current_user)):
    return await fetch_all(
        """
        SELECT la.* FROM linkedin_accounts la
        JOIN campaign_linkedin_accounts cla ON cla.account_id = la.id
        WHERE cla.campaign_id = $1
        ORDER BY la.name
        """,
        campaign_id,
    )


@router.post("/{campaign_id}/accounts", status_code=201)
async def assign_account(campaign_id: str, body: AccountAssign, user_id: str = Depends(get_current_user)):
    await execute(
        "INSERT INTO campaign_linkedin_accounts (campaign_id, account_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        campaign_id, body.account_id,
    )
    return {"ok": True}


@router.delete("/{campaign_id}/accounts/{account_id}", status_code=204)
async def unassign_account(campaign_id: str, account_id: str, user_id: str = Depends(get_current_user)):
    await execute(
        "DELETE FROM campaign_linkedin_accounts WHERE campaign_id=$1 AND account_id=$2",
        campaign_id, account_id,
    )


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
