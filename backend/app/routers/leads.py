from fastapi import APIRouter, Depends, HTTPException
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
    user_id: str = Depends(get_current_user),
):
    offset = (page - 1) * page_size
    rows = await fetch_all(
        "SELECT * FROM leads WHERE campaign_id=$1 ORDER BY created_at DESC LIMIT $2 OFFSET $3",
        campaign_id, page_size, offset,
    )
    total = await fetch_one("SELECT COUNT(*) AS cnt FROM leads WHERE campaign_id=$1", campaign_id)
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
