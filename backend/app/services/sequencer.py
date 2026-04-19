import json
import logging
import random
from datetime import datetime, timedelta, timezone
from app.db import execute, fetch_all, fetch_one

log = logging.getLogger(__name__)

async def schedule_new_lead(lead_id: str) -> None:
    """Entry point: Inject a freshly scraped lead into the DAG from trigger_start."""
    lead = await fetch_one(
        "SELECT id, campaign_id FROM leads WHERE id=$1", lead_id
    )
    if not lead:
        return

    start_node = await fetch_one(
        "SELECT id FROM sequence_nodes WHERE campaign_id=$1 AND node_type='trigger_start' LIMIT 1",
        lead["campaign_id"],
    )
    if not start_node:
        log.warning(f"[sequencer] No trigger_start for campaign {lead['campaign_id']}")
        return

    log.info(f"[sequencer] Injecting new lead {lead_id} into DAG")
    await queue_next_nodes(lead_id, start_node["id"])


async def schedule_sequence(lead_id: str) -> None:
    """Entry point: Resume the sequence for a lead after invite acceptance."""
    lead = await fetch_one(
        "SELECT id, campaign_id, accepted_at FROM leads WHERE id=$1", lead_id
    )
    if not lead or not lead["accepted_at"]:
        return

    start_node = await fetch_one(
        "SELECT id FROM sequence_nodes WHERE campaign_id=$1 AND node_type='trigger_start' LIMIT 1",
        lead["campaign_id"],
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

        elif node_type.startswith("condition_"):
            if node_type == "condition_replied":
                if lead["replied_at"]:
                    await queue_next_nodes(lead_id, target_id, "true", accumulated_delay)
                else:
                    await execute("UPDATE leads SET current_node_id=$1 WHERE id=$2", target_id, lead_id)
            elif node_type == "condition_linkedin_distance":
                if lead.get("linkedin_distance") == "FIRST_DEGREE":
                    await queue_next_nodes(lead_id, target_id, "true", accumulated_delay)
                else:
                    await queue_next_nodes(lead_id, target_id, "false", accumulated_delay)
            elif node_type == "condition_ai_screen":
                from app.services.screener import screen_lead
                prompt = (node["data"] or {}).get("screening_prompt", "")
                verdict = await screen_lead(lead.get("headline", ""), prompt)
                branch = "true" if verdict == "ACCEPT" else "false"
                log.info(f"[sequencer] AI screen for lead {lead_id}: {verdict} → {branch}")
                await queue_next_nodes(lead_id, target_id, branch, accumulated_delay)
            elif node_type == "condition_lead_source":
                configured_sources = (node["data"] or {}).get("sources", [])
                lead_source = lead.get("source", "")
                branch = lead_source if lead_source in configured_sources else "default"
                log.info(f"[sequencer] Source router for lead {lead_id}: source={lead_source} → handle={branch}")
                await queue_next_nodes(lead_id, target_id, branch, accumulated_delay)

        elif node_type == "split":
            weights = (node.get("data") or {}).get("weights", {
                "true": {"alpha": 1, "beta": 1},
                "false": {"alpha": 1, "beta": 1},
            })
            sample_true = random.betavariate(
                weights["true"]["alpha"], weights["true"]["beta"]
            )
            sample_false = random.betavariate(
                weights["false"]["alpha"], weights["false"]["beta"]
            )
            chosen_arm = "true" if sample_true >= sample_false else "false"
            await execute(
                "UPDATE leads SET path_history = path_history || $1::jsonb WHERE id=$2",
                json.dumps([{"split_node_id": str(target_id), "arm": chosen_arm}]),
                lead_id,
            )
            log.info(f"[sequencer] Split node {target_id}: chose arm '{chosen_arm}' for lead {lead_id}")
            await queue_next_nodes(lead_id, target_id, chosen_arm, accumulated_delay)

        elif node_type.startswith("event_"):
            # All events park the lead until the webhook triggers evaluation
            if node_type == "event_invite_accepted" and lead.get("accepted_at"):
                await queue_next_nodes(lead_id, target_id, "true", accumulated_delay)
            elif node_type == "event_email_opened" and lead.get("email_opened_at"):
                await queue_next_nodes(lead_id, target_id, "true", accumulated_delay)
            elif node_type == "event_link_clicked" and lead.get("link_clicked_at"):
                await queue_next_nodes(lead_id, target_id, "true", accumulated_delay)
            else:
                await execute("UPDATE leads SET current_node_id=$1 WHERE id=$2", target_id, lead_id)

async def evaluate_conditions(lead_id: str) -> None:
    """Called when lead state changes (e.g. reply received, invite accepted)."""
    log.info(f"[sequencer] Re-evaluating conditions for lead {lead_id}")
    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", lead_id)
    
    if not lead:
        log.warning(f"[sequencer] Lead {lead_id} not found during evaluate_conditions")
        return
        
    if not lead["current_node_id"]:
        log.debug(f"[sequencer] Lead {lead_id} has no current_node_id; skipping re-evaluation")
        return
    
    node = await fetch_one("SELECT node_type FROM sequence_nodes WHERE id=$1", lead["current_node_id"])
    if not node:
        log.warning(f"[sequencer] current_node_id {lead['current_node_id']} not found for lead {lead_id}")
        return

    node_type = node["node_type"]
    log.debug(f"[sequencer] Lead {lead_id} currently at node {node_type} ({lead['current_node_id']})")

    should_advance = False
    
    if node_type == "condition_replied" and lead.get("replied_at"):
        should_advance = True
    elif node_type == "event_invite_accepted" and lead.get("accepted_at"):
        should_advance = True
    elif node_type == "event_email_opened" and lead.get("email_opened_at"):
        should_advance = True
    elif node_type == "event_link_clicked" and lead.get("link_clicked_at"):
        should_advance = True

    if should_advance:
        log.info(f"[sequencer] Lead {lead_id} satisfied {node_type}. Advancing True branch.")
        await queue_next_nodes(lead_id, lead["current_node_id"], "true")
        await execute("UPDATE leads SET current_node_id=NULL WHERE id=$1", lead_id)
    else:
        log.debug(f"[sequencer] Lead {lead_id} is at {node_type} but condition not met yet; no-op.")
