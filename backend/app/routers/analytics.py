from fastapi import APIRouter, Depends

from app.auth import get_current_user
from app.db import fetch_all, fetch_one

router = APIRouter()


@router.get("/{campaign_id}")
async def campaign_analytics(
    campaign_id: str,
    user_id: str = Depends(get_current_user),
):
    """Rich analytics for a single campaign: funnel, daily activity, channel breakdown."""

    # Funnel counts
    funnel = await fetch_one(
        """
        SELECT
            COUNT(*) AS total_leads,
            COUNT(*) FILTER (WHERE status='active') AS active,
            COUNT(*) FILTER (WHERE invited_at IS NOT NULL) AS invited,
            COUNT(*) FILTER (WHERE accepted_at IS NOT NULL) AS accepted,
            COUNT(*) FILTER (WHERE replied_at IS NOT NULL) AS replied,
            COUNT(*) FILTER (WHERE status='stopped') AS stopped
        FROM leads
        WHERE campaign_id=$1
        """,
        campaign_id,
    )

    # Event counts by type
    event_counts = await fetch_all(
        """
        SELECT event_type, COUNT(*) AS cnt
        FROM events
        WHERE campaign_id=$1
        GROUP BY event_type
        ORDER BY cnt DESC
        """,
        campaign_id,
    )

    # Channel breakdown
    channel_breakdown = await fetch_all(
        """
        SELECT channel, COUNT(*) AS cnt
        FROM events
        WHERE campaign_id=$1 AND channel IS NOT NULL
        GROUP BY channel
        ORDER BY cnt DESC
        """,
        campaign_id,
    )

    # Daily activity (last 30 days)
    daily_activity = await fetch_all(
        """
        SELECT
            occurred_at::date AS day,
            COUNT(*) AS events,
            COUNT(DISTINCT lead_id) AS unique_leads
        FROM events
        WHERE campaign_id=$1 AND occurred_at > NOW() - INTERVAL '30 days'
        GROUP BY day
        ORDER BY day
        """,
        campaign_id,
    )

    # Conversion rates
    total = funnel["total_leads"] or 1
    rates = {
        "invite_rate": round((funnel["invited"] / total) * 100, 1),
        "accept_rate": round((funnel["accepted"] / max(funnel["invited"], 1)) * 100, 1),
        "reply_rate": round((funnel["replied"] / max(funnel["accepted"], 1)) * 100, 1),
    }

    return {
        "funnel": funnel,
        "rates": rates,
        "event_counts": event_counts,
        "channel_breakdown": channel_breakdown,
        "daily_activity": daily_activity,
    }


@router.get("/{campaign_id}/conversions")
async def campaign_conversions(
    campaign_id: str,
    user_id: str = Depends(get_current_user),
):
    """Conversion goal tracking for a campaign: how many leads hit each goal type."""
    goals = await fetch_all(
        """
        SELECT
            e.event_type AS goal_event,
            COUNT(DISTINCT e.lead_id) AS converted,
            MIN(e.occurred_at) AS first_conversion,
            MAX(e.occurred_at) AS last_conversion
        FROM events e
        JOIN leads l ON l.id = e.lead_id AND l.campaign_id=$1
        WHERE e.event_type IN ('reply', 'positive_reply', 'meeting_booked', 'link_clicked')
        GROUP BY e.event_type
        ORDER BY converted DESC
        """,
        campaign_id,
    )
    total_leads = await fetch_one(
        "SELECT COUNT(*) AS cnt FROM leads WHERE campaign_id=$1", campaign_id
    )
    total = total_leads["cnt"] or 1
    return {
        "total_leads": total,
        "goals": [
            {
                **dict(g),
                "conversion_rate": round((g["converted"] / total) * 100, 1),
            }
            for g in goals
        ],
    }
