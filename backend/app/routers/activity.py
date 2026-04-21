import json
import logging

from fastapi import APIRouter, Depends, Query

from app.auth import get_current_user
from app.db import execute, fetch_all

router = APIRouter()
log = logging.getLogger(__name__)


async def log_activity(action: str, detail: str = None, user_id: str = None,
                       campaign_id: str = None, lead_id: str = None, meta: dict = None) -> None:
    """Write an activity log entry. Call from any service or router."""
    await execute(
        """INSERT INTO activity_log (user_id, campaign_id, lead_id, action, detail, meta)
           VALUES ($1, $2, $3, $4, $5, $6)""",
        user_id, campaign_id, lead_id, action, detail, json.dumps(meta or {}),
    )


@router.get("")
async def list_activity(
    campaign_id: str | None = None,
    limit: int = Query(default=50, le=200),
    user: dict = Depends(get_current_user),
):
    if campaign_id:
        rows = await fetch_all(
            "SELECT * FROM activity_log WHERE campaign_id=$1 ORDER BY created_at DESC LIMIT $2",
            campaign_id, limit,
        )
    else:
        rows = await fetch_all(
            "SELECT * FROM activity_log ORDER BY created_at DESC LIMIT $1",
            limit,
        )
    return {"activity": rows}
