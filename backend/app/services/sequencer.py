import logging
from datetime import timedelta

from app.db import execute, fetch_all, fetch_one

log = logging.getLogger(__name__)


async def schedule_sequence(lead_id: str) -> None:
    """After acceptance, insert queue rows for all remaining sequence steps."""
    lead = await fetch_one(
        "SELECT campaign_id, accepted_at FROM leads WHERE id=$1", lead_id
    )
    if not lead:
        log.warning(f"[sequencer] Lead {lead_id} not found")
        return
    if not lead["accepted_at"]:
        log.warning(f"[sequencer] Lead {lead_id} has no accepted_at — skipping")
        return

    steps = await fetch_all(
        """
        SELECT id, step_order, channel, delay_days
        FROM sequence_steps
        WHERE campaign_id=$1
        ORDER BY step_order ASC
        """,
        lead["campaign_id"],
    )

    if not steps:
        log.info(f"[sequencer] No sequence steps for campaign {lead['campaign_id']}")
        return

    base = lead["accepted_at"]
    cumulative_days = 0

    for step in steps:
        if step["step_order"] == 0:
            # Step 0 is the invite — already done
            continue

        cumulative_days += step["delay_days"]
        scheduled_at = base + timedelta(days=cumulative_days)

        # Idempotency check
        existing = await fetch_one(
            "SELECT 1 FROM queue WHERE lead_id=$1 AND step_id=$2 LIMIT 1",
            lead_id, step["id"],
        )
        if existing:
            continue

        await execute(
            """
            INSERT INTO queue
                (campaign_id, lead_id, step_id, channel, status, scheduled_at, payload)
            VALUES ($1, $2, $3, $4, 'queued', $5, '{}')
            ON CONFLICT DO NOTHING
            """,
            lead["campaign_id"],
            lead_id,
            step["id"],
            step["channel"],
            scheduled_at,
        )
        log.info(
            f"[sequencer] Lead {lead_id} step {step['step_order']} "
            f"({step['channel']}) scheduled for {scheduled_at}"
        )
