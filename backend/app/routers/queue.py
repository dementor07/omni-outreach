from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import fetch_all

router = APIRouter()


@router.get("")
async def list_queue(
    campaign_id: str | None = None,
    status: str | None = None,
    limit: int = 100,
    user_id: str = Depends(get_current_user),
):
    conditions = []
    params: list = []

    if campaign_id:
        params.append(campaign_id)
        conditions.append(f"q.campaign_id=${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"q.status=${len(params)}")

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)

    rows = await fetch_all(
        f"""
        SELECT q.*, l.first_name, l.last_name, l.linkedin_url
        FROM queue q
        JOIN leads l ON l.id=q.lead_id
        {where}
        ORDER BY q.scheduled_at
        LIMIT ${len(params)}
        """,
        *params,
    )
    return {"tasks": rows}


@router.get("/stats")
async def queue_stats(user_id: str = Depends(get_current_user)):
    rows = await fetch_all(
        "SELECT channel, status, COUNT(*) AS cnt FROM queue GROUP BY channel, status ORDER BY channel, status"
    )
    return {"stats": rows}
