import logging
from datetime import datetime, timedelta, timezone
from app.db import execute, fetch_all, fetch_one

log = logging.getLogger(__name__)

async def schedule_sequence(lead_id: str) -> None:
    """Entry point: Start the sequence for a lead (usually after acceptance)."""
    lead = await fetch_one(
        "SELECT id, campaign_id, accepted_at FROM leads WHERE id=$1", lead_id
    )
    if not lead or not lead["accepted_at"]:
        return

    # Find trigger_start node
    start_node = await fetch_one(
        "SELECT id FROM sequence_nodes WHERE campaign_id=$1 AND node_type='trigger_start' LIMIT 1",
        lead["campaign_id"]
    )
    
    if not start_node:
        log.warning(f"[sequencer] No trigger_start for campaign {lead['campaign_id']}")
        return

    await queue_next_nodes(lead_id, start_node["id"])

async def queue_next_nodes(
    lead_id: str,
    source_node_id: str,
    handle: str = "default",
    accumulated_delay: timedelta = timedelta(0),
) -> None:
    """Finds target nodes from source_node and handles them (queue or recursive evaluate)."""
    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", lead_id)
    if not lead: return

    edges = await fetch_all(
        "SELECT target_node_id FROM sequence_edges WHERE source_node_id=$1 AND source_handle=$2",
        source_node_id, handle,
    )

    for edge in edges:
        target_id = edge["target_node_id"]
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", target_id)
        if not node: continue

        node_type = node["node_type"]

        if node_type.startswith("action_"):
            channel = node_type.replace("action_", "")
            scheduled_at = datetime.now(timezone.utc) + accumulated_delay
            await execute(
                """
                INSERT INTO queue (campaign_id, lead_id, node_id, channel, status, scheduled_at)
                VALUES ($1, $2, $3, $4, 'queued', $5)
                ON CONFLICT DO NOTHING
                """,
                lead["campaign_id"], lead_id, target_id, channel, scheduled_at,
            )
            log.info(f"[sequencer] Queued {channel} for lead {lead_id} at {scheduled_at}")

        elif node_type == "delay":
            # Accumulate delay and continue graph traversal — do NOT recurse immediately
            delay_days = (node["data"] or {}).get("delay_days", 1)
            new_delay = accumulated_delay + timedelta(days=delay_days)
            await queue_next_nodes(lead_id, target_id, "default", new_delay)

        elif node_type == "condition_replied":
            if lead["replied_at"]:
                await queue_next_nodes(lead_id, target_id, "true", accumulated_delay)
            else:
                # Park lead here; webhook will call evaluate_conditions when reply arrives
                await execute("UPDATE leads SET current_node_id=$1 WHERE id=$2", target_id, lead_id)

async def evaluate_conditions(lead_id: str) -> None:
    """Called when lead state changes (e.g. reply received)."""
    lead = await fetch_one("SELECT id, current_node_id, replied_at FROM leads WHERE id=$1", lead_id)
    if not lead or not lead["current_node_id"]: return
    
    node = await fetch_one("SELECT node_type FROM sequence_nodes WHERE id=$1", lead["current_node_id"])
    if node and node["node_type"] == "condition_replied":
        if lead["replied_at"]:
            await queue_next_nodes(lead_id, lead["current_node_id"], "true")
            await execute("UPDATE leads SET current_node_id=NULL WHERE id=$1", lead_id)
