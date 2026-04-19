from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

router = APIRouter()


class LeadImport(BaseModel):
    linkedin_url: str
    email: str | None = None
    phone: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    headline: str | None = None
    company: str | None = None
    source: str = "manual"


@router.get("")
async def list_leads(
    campaign_id: str,
    page: int = 1,
    page_size: int = 50,
    search: Optional[str] = None,
    status: Optional[str] = None,
    user_id: str = Depends(get_current_user),
):
    offset = (page - 1) * page_size
    conditions = ["campaign_id=$1"]
    params: list = [campaign_id]
    idx = 2

    if status:
        conditions.append(f"status=${idx}")
        params.append(status)
        idx += 1

    if search:
        conditions.append(
            f"(first_name ILIKE ${idx} OR last_name ILIKE ${idx} OR company ILIKE ${idx} OR email ILIKE ${idx} OR headline ILIKE ${idx})"
        )
        params.append(f"%{search}%")
        idx += 1

    where = " AND ".join(conditions)
    rows = await fetch_all(
        f"SELECT * FROM leads WHERE {where} ORDER BY created_at DESC LIMIT ${idx} OFFSET ${idx + 1}",
        *params, page_size, offset,
    )
    total = await fetch_one(f"SELECT COUNT(*) AS cnt FROM leads WHERE {where}", *params)
    return {"leads": rows, "total": total["cnt"], "page": page, "page_size": page_size}


@router.get("/{lead_id}")
async def get_lead(lead_id: str, user_id: str = Depends(get_current_user)):
    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    events = await fetch_all(
        "SELECT event_type, channel, meta, occurred_at FROM events WHERE lead_id=$1 ORDER BY occurred_at ASC",
        lead_id,
    )
    return {**lead, "timeline": events}


@router.post("/import")
async def import_leads(
    campaign_id: str,
    leads: list[LeadImport],
    user_id: str = Depends(get_current_user),
):
    imported = 0
    skipped = 0
    for lead in leads:
        existing = await fetch_one(
            "SELECT id FROM leads WHERE campaign_id=$1 AND linkedin_url=$2",
            campaign_id, lead.linkedin_url,
        )
        if existing:
            skipped += 1
            continue
        await execute(
            """
            INSERT INTO leads
                (campaign_id, linkedin_url, email, phone, first_name, last_name,
                 headline, company, source)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT DO NOTHING
            """,
            campaign_id, lead.linkedin_url, lead.email, lead.phone,
            lead.first_name, lead.last_name, lead.headline, lead.company, lead.source,
        )
        imported += 1
    return {"imported": imported, "skipped": skipped}


@router.delete("/{lead_id}", status_code=204)
async def stop_lead(lead_id: str, user_id: str = Depends(get_current_user)):
    lead = await fetch_one("SELECT id FROM leads WHERE id=$1", lead_id)
    if not lead:
        raise HTTPException(status_code=404, detail="Lead not found")
    await execute("UPDATE leads SET status='stopped', stopped_at=NOW() WHERE id=$1", lead_id)
    await execute(
        "UPDATE queue SET status='skipped' WHERE lead_id=$1 AND status IN ('queued','locked')",
        lead_id,
    )


class BulkAction(BaseModel):
    lead_ids: list[str]
    action: str  # "stop", "requeue", "delete", "move_campaign", "add_tag"
    target_campaign_id: str | None = None
    tag: str | None = None


@router.post("/bulk")
async def bulk_lead_action(body: BulkAction, user_id: str = Depends(get_current_user)):
    """Perform bulk operations on multiple leads."""
    if not body.lead_ids:
        raise HTTPException(400, "No leads selected")

    affected = 0
    if body.action == "stop":
        for lid in body.lead_ids:
            await execute("UPDATE leads SET status='stopped', stopped_at=NOW() WHERE id=$1", lid)
            await execute("UPDATE queue SET status='skipped' WHERE lead_id=$1 AND status IN ('queued','locked')", lid)
            affected += 1

    elif body.action == "requeue":
        for lid in body.lead_ids:
            await execute("UPDATE leads SET status='active', stopped_at=NULL WHERE id=$1", lid)
            affected += 1

    elif body.action == "delete":
        for lid in body.lead_ids:
            await execute("DELETE FROM queue WHERE lead_id=$1", lid)
            await execute("DELETE FROM events WHERE lead_id=$1", lid)
            await execute("DELETE FROM leads WHERE id=$1", lid)
            affected += 1

    elif body.action == "move_campaign":
        if not body.target_campaign_id:
            raise HTTPException(400, "target_campaign_id required for move_campaign")
        for lid in body.lead_ids:
            await execute("UPDATE leads SET campaign_id=$1 WHERE id=$2", body.target_campaign_id, lid)
            affected += 1

    else:
        raise HTTPException(400, f"Unknown action: {body.action}")

    return {"affected": affected, "action": body.action}
