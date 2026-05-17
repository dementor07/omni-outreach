import json
import logging
import random
import uuid
from datetime import UTC, datetime, timedelta

from app.core.events import ActionCommand, ChannelType, LeadContext
from app.db import execute, fetch_all, fetch_one
from app.services import notifier
from app.services.bus import bus

log = logging.getLogger(__name__)


async def schedule_new_lead(lead_id: str) -> None:
    """Entry point: Inject a freshly scraped lead into the DAG from trigger_start."""
    lead = await fetch_one("SELECT id, campaign_id FROM leads WHERE id=$1", lead_id)
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
    lead = await fetch_one("SELECT id, campaign_id, accepted_at FROM leads WHERE id=$1", lead_id)
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
    if not lead:
        return

    edges = await fetch_all(
        "SELECT target_node_id FROM sequence_edges WHERE source_node_id=$1 AND source_handle=$2",
        source_node_id,
        handle,
    )

    for edge in edges:
        target_id = edge["target_node_id"]
        node = await fetch_one("SELECT * FROM sequence_nodes WHERE id=$1", target_id)
        if not node:
            continue

        node_type = node["node_type"]

        if node_type.startswith("action_"):
            channel_str = node_type.replace("action_", "")
            task_id = uuid.uuid4()

            # Map to ChannelType enum
            try:
                channel = ChannelType(channel_str)
            except ValueError:
                log.error(f"[sequencer] Unknown channel type: {channel_str}")
                continue

            # Create the SOTA ActionCommand
            command = ActionCommand(
                command_id=uuid.uuid4(),
                task_id=task_id,  # Legacy queue mirror id until the queue table is retired.
                channel=channel,
                lead=LeadContext(
                    id=lead["id"],
                    campaign_id=lead["campaign_id"],
                    email=lead.get("email"),
                    linkedin_url=lead.get("linkedin_url"),
                    first_name=lead.get("first_name"),
                    last_name=lead.get("last_name"),
                    company=lead.get("company"),
                    chat_id=lead.get("chat_id"),
                    extra_data=dict(lead.get("extra_data") or {}),
                ),
                payload=(node["data"] or {}),
                metadata={"node_id": str(target_id), "accumulated_delay_seconds": accumulated_delay.total_seconds()},
            )

            # Brain/Muscle authority gate (see config.execution_mode).
            from app.config import settings as _settings

            mode = (_settings.execution_mode or "shadow").lower()
            if mode in ("shadow", "muscle"):
                await bus.publish_command(command)

            if mode in ("shadow", "legacy"):
                scheduled_at = datetime.now(UTC) + accumulated_delay
                await execute(
                    """
                    INSERT INTO queue (id, campaign_id, lead_id, node_id, channel, status, scheduled_at)
                    VALUES ($1, $2, $3, $4, $5, 'queued', $6)
                    ON CONFLICT DO NOTHING
                    """,
                    task_id,
                    lead["campaign_id"],
                    lead_id,
                    target_id,
                    channel_str,
                    scheduled_at,
                )
            log.info(f"[sequencer] dispatched {channel_str} for lead {lead_id} (mode={mode})")

        elif node_type == "delay":
            # SOTA: Delays are handled by Flink's timer service.
            # We simply log the arrival at the delay node.
            log.info(f"[sequencer] Lead {lead_id} reached delay node {target_id}. Flink takes over.")
            await execute("UPDATE leads SET current_node_id=$1 WHERE id=$2", target_id, lead_id)

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
            elif node_type == "condition_has_field":
                field_name = (node["data"] or {}).get("field", "email")
                has_value = bool(lead.get(field_name))
                branch = "true" if has_value else "false"
                log.info(f"[sequencer] Field check for lead {lead_id}: field={field_name} present={has_value}")
                await queue_next_nodes(lead_id, target_id, branch, accumulated_delay)
            elif node_type == "condition_reply_intent":
                category = (lead.get("last_reply_category") or "").strip()
                if not category:
                    # No classified reply yet — park here; webhook handler will
                    # re-enter via evaluate_conditions() once a reply arrives.
                    await execute(
                        "UPDATE leads SET current_node_id=$1 WHERE id=$2",
                        target_id,
                        lead_id,
                    )
                    log.info(f"[sequencer] Reply-intent parking lead {lead_id} at {target_id}")
                else:
                    branch = category  # positive|negative|neutral|out_of_office|unsubscribe|bounce
                    log.info(f"[sequencer] Reply intent for lead {lead_id}: {branch}")
                    await queue_next_nodes(lead_id, target_id, branch, accumulated_delay)

        elif node_type == "split":
            weights = (node.get("data") or {}).get(
                "weights",
                {
                    "true": {"alpha": 1, "beta": 1},
                    "false": {"alpha": 1, "beta": 1},
                },
            )
            sample_true = random.betavariate(weights["true"]["alpha"], weights["true"]["beta"])
            sample_false = random.betavariate(weights["false"]["alpha"], weights["false"]["beta"])
            chosen_arm = "true" if sample_true >= sample_false else "false"
            await execute(
                "UPDATE leads SET path_history = path_history || $1::jsonb WHERE id=$2",
                json.dumps([{"split_node_id": str(target_id), "arm": chosen_arm}]),
                lead_id,
            )
            log.info(f"[sequencer] Split node {target_id}: chose arm '{chosen_arm}' for lead {lead_id}")
            await queue_next_nodes(lead_id, target_id, chosen_arm, accumulated_delay)

        elif node_type == "control_parallel_fork":
            # Fire all branches (up to 5) simultaneously
            log.info(f"[sequencer] Parallel fork {target_id} for lead {lead_id}")
            for i in range(1, 6):
                await queue_next_nodes(lead_id, target_id, f"branch_{i}", accumulated_delay)

        elif node_type == "human_approval":
            # Open a new approvals row and park. Resume on POST /approvals/{id}/resolve.
            existing = await fetch_one(
                "SELECT id FROM approvals WHERE lead_id=$1 AND node_id=$2 AND status='pending'",
                lead_id,
                target_id,
            )
            if not existing:
                title = (node["data"] or {}).get("title") or "Approval required"
                payload = (node["data"] or {}).get("payload") or {}
                await execute(
                    """
                    INSERT INTO approvals (campaign_id, lead_id, node_id, title, payload)
                    VALUES ($1, $2, $3, $4, $5)
                    """,
                    lead["campaign_id"],
                    lead_id,
                    target_id,
                    title,
                    json.dumps(payload),
                )
                log.info(f"[sequencer] Opened approval for lead {lead_id} at node {target_id}")
                # Notify operators so the approval is not silent
                await notifier.dispatch_alert(
                    title=f"Approval required: {title}",
                    body=f"Lead {lead_id} is parked at approval node and requires manual review.",
                    context={
                        "lead_id": str(lead_id),
                        "node_id": str(target_id),
                        "campaign_id": str(lead["campaign_id"]),
                    },
                )
            await execute(
                "UPDATE leads SET current_node_id=$1 WHERE id=$2",
                target_id,
                lead_id,
            )

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

    advance_handle: str | None = None

    if node_type == "condition_replied" and lead.get("replied_at"):
        advance_handle = "true"
    elif node_type == "event_invite_accepted" and lead.get("accepted_at"):
        advance_handle = "true"
    elif node_type == "event_email_opened" and lead.get("email_opened_at"):
        advance_handle = "true"
    elif node_type == "event_link_clicked" and lead.get("link_clicked_at"):
        advance_handle = "true"
    elif node_type == "condition_reply_intent" and lead.get("last_reply_category"):
        advance_handle = lead["last_reply_category"]
    # human_approval is unparked by the approvals router calling
    # resume_from_approval(); it does not self-advance here.

    if advance_handle:
        log.info(f"[sequencer] Lead {lead_id} satisfied {node_type}. Advancing handle '{advance_handle}'.")
        await queue_next_nodes(lead_id, lead["current_node_id"], advance_handle)
        await execute("UPDATE leads SET current_node_id=NULL WHERE id=$1", lead_id)
    else:
        log.debug(f"[sequencer] Lead {lead_id} is at {node_type} but condition not met yet; no-op.")


async def resume_from_approval(lead_id: str, approval_id: str, resolution: str) -> None:
    """Unpark a lead that was parked at a human_approval node.

    resolution is one of 'approve' | 'reject'. Advances the matching handle.
    """
    lead = await fetch_one("SELECT * FROM leads WHERE id=$1", lead_id)
    if not lead or not lead.get("current_node_id"):
        log.warning(f"[sequencer] resume_from_approval: lead {lead_id} has no current_node_id")
        return
    handle = "approve" if resolution == "approve" else "reject"
    log.info(f"[sequencer] Resuming lead {lead_id} from approval {approval_id} via handle '{handle}'")
    await queue_next_nodes(lead_id, lead["current_node_id"], handle)
    await execute("UPDATE leads SET current_node_id=NULL WHERE id=$1", lead_id)


async def check_reply_intent_timeouts() -> None:
    """Finds leads parked at condition_reply_intent longer than timeout_days and routes them."""
    log.info("[sequencer] Checking for condition_reply_intent timeouts...")
    query = """
        SELECT l.id, l.current_node_id, sn.data,
               (SELECT MAX(sent_at) FROM queue WHERE lead_id = l.id AND status = 'sent') as last_contact_at
        FROM leads l
        JOIN sequence_nodes sn ON l.current_node_id = sn.id
        WHERE sn.node_type = 'condition_reply_intent'
          AND l.current_node_id IS NOT NULL
    """
    rows = await fetch_all(query)
    now = datetime.now(UTC)
    for row in rows:
        timeout_days = (row["data"] or {}).get("timeout_days", 7)
        last_contact = row["last_contact_at"]
        if not last_contact:
            continue

        if last_contact.tzinfo is None:
            last_contact = last_contact.replace(tzinfo=UTC)

        elapsed = (now - last_contact).days
        if elapsed >= int(timeout_days):
            log.info(
                f"[sequencer] Lead {row['id']} timed out at reply intent node (elapsed: {elapsed}d, timeout: {timeout_days}d). Routing to 'timeout' handle."
            )
            await queue_next_nodes(str(row["id"]), str(row["current_node_id"]), "timeout")
            await execute("UPDATE leads SET current_node_id=NULL WHERE id=$1", row["id"])
