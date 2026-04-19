from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import fetch_one, fetch_all

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


@router.get("/daily-activity")
async def daily_activity(user_id: str = Depends(get_current_user)):
    """Last 14 days of queue activity grouped by day and status."""
    rows = await fetch_all(
        """
        SELECT
            DATE(executed_at) AS day,
            status,
            COUNT(*) AS cnt
        FROM queue
        WHERE executed_at >= CURRENT_DATE - INTERVAL '14 days'
        GROUP BY DATE(executed_at), status
        ORDER BY day
        """
    )
    return [dict(r) for r in rows]


@router.get("/response-rates")
async def response_rates(user_id: str = Depends(get_current_user)):
    """Per-campaign invite→accept and accept→reply rates."""
    rows = await fetch_all(
        """
        SELECT
            c.id,
            c.name,
            COUNT(l.id)                                                 AS total,
            COUNT(l.id) FILTER (WHERE l.invited_at  IS NOT NULL)        AS invited,
            COUNT(l.id) FILTER (WHERE l.accepted_at IS NOT NULL)        AS accepted,
            COUNT(l.id) FILTER (WHERE l.replied_at  IS NOT NULL)        AS replied
        FROM campaigns c
        LEFT JOIN leads l ON l.campaign_id = c.id
        GROUP BY c.id, c.name
        ORDER BY total DESC
        LIMIT 10
        """
    )
    return [dict(r) for r in rows]
