from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import fetch_one

router = APIRouter()


@router.get("/stats")
async def overview_stats(user_id: str = Depends(get_current_user)):
    """
    Aggregate lead funnel counts across all campaigns.
    Derived from the leads table so numbers reflect real state,
    not queue throughput proxies.
    """
    row = await fetch_one(
        """
        SELECT
            COUNT(*)                                                    AS total_leads,
            COUNT(*) FILTER (WHERE invited_at  IS NOT NULL)             AS invited,
            COUNT(*) FILTER (WHERE accepted_at IS NOT NULL)             AS accepted,
            COUNT(*) FILTER (WHERE status = 'active'
                             AND   accepted_at IS NOT NULL)             AS sent
        FROM leads
        """
    )
    return {
        "total_leads": int(row["total_leads"] or 0),
        "invited":     int(row["invited"]     or 0),
        "accepted":    int(row["accepted"]    or 0),
        "sent":        int(row["sent"]        or 0),
    }
