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


async def claim_race_winner_if_applicable(lead_id: str, source_node_id: str) -> None:
    """If ``source_node_id``'s upstream is a control_race node, record the winner.

    Called by the dispatcher right before _mark_sent so the first delivery that
    succeeds in a racing branch crowns that branch and cancels its siblings.
    Safe to call for every action — it no-ops if no race is upstream.
    """
    parents = await fetch_all(
        """
        SELECT se.source_node_id AS race_id, se.source_handle AS branch, sn.node_type
        FROM sequence_edges se
        JOIN sequence_nodes sn ON sn.id = se.source_node_id
        WHERE se.target_node_id = $1 AND sn.node_type = 'control_race'
        """,
        source_node_id,
    )
    for p in parents:
        await execute(
            """
            INSERT INTO race_winners (lead_id, race_node_id, winning_branch)
            VALUES ($1, $2, $3) ON CONFLICT DO NOTHING
            """,
            lead_id,
            p["race_id"],
            p["branch"],
        )
        log.info(
            f"[sequencer] race {p['race_id']} crowned branch '{p['branch']}' for lead {lead_id}"
        )


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

    # control_race short-circuit: if this lead has already crowned a winner for
    # this race node, drop edges from losing branches so cancellations propagate.
    winner_row = await fetch_one(
        "SELECT winning_branch FROM race_winners WHERE lead_id=$1 AND race_node_id=$2",
        lead_id,
        source_node_id,
    )
    if winner_row and handle != winner_row["winning_branch"]:
        log.info(
            f"[sequencer] race {source_node_id}: lead {lead_id} losing branch '{handle}' cancelled"
        )
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

        # Loop iteration cap (Gap 8). If node.data.max_iterations is set, count
        # how many times this lead has previously visited this node in
        # path_history and refuse to re-enter past the cap.
        max_iter = (node["data"] or {}).get("max_iterations")
        if max_iter is not None:
            try:
                cap = int(max_iter)
            except (TypeError, ValueError):
                cap = 0
            if cap > 0:
                visits_row = await fetch_one(
                    """
                    SELECT COALESCE((
                        SELECT COUNT(*) FROM jsonb_array_elements(COALESCE(path_history, '[]'::jsonb)) e
                        WHERE e->>'visited_node_id' = $2
                    ), 0) AS n
                    FROM leads WHERE id=$1
                    """,
                    lead_id,
                    str(target_id),
                )
                visits = int(visits_row["n"]) if visits_row else 0
                if visits >= cap:
                    log.info(
                        f"[sequencer] iteration cap reached for lead {lead_id} at node {target_id} ({visits}/{cap}); skipping"
                    )
                    continue
                await execute(
                    "UPDATE leads SET path_history = path_history || $1::jsonb, "
                    "iteration_count = iteration_count + 1 WHERE id=$2",
                    json.dumps([{"visited_node_id": str(target_id), "at": datetime.now(UTC).isoformat()}]),
                    lead_id,
                )

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
            # Compute deterministic wait from node.data. Supports both legacy
            # (delay_days: int) and the current frontend keys (delay_value + delay_unit).
            d = node["data"] or {}
            unit = str(d.get("delay_unit") or "days").lower()
            try:
                amount = float(d.get("delay_value") if d.get("delay_value") is not None else d.get("delay_days", 0))
            except (TypeError, ValueError):
                amount = 0.0
            unit_seconds = {"seconds": 1, "minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800}.get(unit, 86400)
            extra_seconds = amount * unit_seconds
            new_accumulated = accumulated_delay + timedelta(seconds=extra_seconds)
            log.info(f"[sequencer] delay node {target_id}: +{amount} {unit} (cumulative {new_accumulated.total_seconds()}s)")
            await execute("UPDATE leads SET current_node_id=$1 WHERE id=$2", target_id, lead_id)
            # Recurse into the next nodes with the cumulative delay; the queue insert
            # will fire scheduled_at = now() + new_accumulated downstream.
            await queue_next_nodes(lead_id, target_id, "default", new_accumulated)

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
            elif node_type == "condition_lead_quota_reached":
                # Branch on whether the campaign's lead-gen credit budget is
                # exhausted. data.config_id (optional) narrows to a single
                # lead_gen_config; without it, sum across all configs for this
                # campaign. Returns 'true' when used >= budget, else 'false'.
                d = node["data"] or {}
                cfg_id = d.get("config_id")
                if cfg_id:
                    row = await fetch_one(
                        """
                        SELECT
                          COALESCE(lgc.credit_budget, 0) AS budget,
                          COALESCE((
                            SELECT SUM(credits_consumed) FROM lead_gen_runs
                            WHERE config_id = lgc.id AND status='done'
                          ), 0) AS used
                        FROM lead_gen_configs lgc WHERE lgc.id=$1
                        """,
                        cfg_id,
                    )
                else:
                    row = await fetch_one(
                        """
                        SELECT
                          COALESCE(SUM(lgc.credit_budget), 0) AS budget,
                          COALESCE((
                            SELECT SUM(credits_consumed) FROM lead_gen_runs r
                            WHERE r.campaign_id = $1 AND r.status='done'
                          ), 0) AS used
                        FROM lead_gen_configs lgc WHERE lgc.campaign_id = $1
                        """,
                        lead["campaign_id"],
                    )
                budget = int(row["budget"]) if row else 0
                used = int(row["used"]) if row else 0
                exhausted = budget > 0 and used >= budget
                branch = "true" if exhausted else "false"
                log.info(
                    f"[sequencer] quota check campaign={lead['campaign_id']} "
                    f"config={cfg_id or 'all'} used={used}/{budget} → {branch}"
                )
                await queue_next_nodes(lead_id, target_id, branch, accumulated_delay)
            elif node_type == "condition_has_field":
                d = node["data"] or {}
                field_name = d.get("field_name") or d.get("field") or "email"
                has_value = bool(lead.get(field_name))
                branch = "true" if has_value else "false"
                log.info(f"[sequencer] Field check for lead {lead_id}: field={field_name} present={has_value}")
                await queue_next_nodes(lead_id, target_id, branch, accumulated_delay)
            elif node_type == "condition_field_equals":
                # Multi-output router. Operator picks a lead field + a list of expected
                # values; each value becomes a named handle. Anything else goes to 'default'.
                d = node["data"] or {}
                field_name = str(d.get("field_name") or d.get("field") or "industry")
                expected = d.get("values") or []
                if not isinstance(expected, list):
                    expected = []
                raw = lead.get(field_name)
                if raw is None and isinstance(lead.get("extra_data"), dict):
                    raw = lead["extra_data"].get(field_name)
                actual = str(raw).strip() if raw is not None else ""
                branch = actual if actual in [str(v) for v in expected] else "default"
                log.info(
                    f"[sequencer] field_equals lead {lead_id}: {field_name}={actual!r} → handle={branch}"
                )
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
            # N-arm Thompson Sampling bandit. Arms are operator-named in data.arms
            # (list of strings). Per-arm beta priors live in data.weights[name].
            # Legacy 2-arm campaigns with weights.true/weights.false still work.
            d = node.get("data") or {}
            arms = d.get("arms") or list((d.get("weights") or {}).keys()) or ["true", "false"]
            weights = d.get("weights") or {}
            samples: dict[str, float] = {}
            for arm in arms:
                w = weights.get(arm) or {"alpha": 1, "beta": 1}
                try:
                    samples[arm] = random.betavariate(float(w.get("alpha", 1)), float(w.get("beta", 1)))
                except (TypeError, ValueError):
                    samples[arm] = random.random()
            chosen_arm = max(samples, key=samples.get)
            await execute(
                "UPDATE leads SET path_history = path_history || $1::jsonb WHERE id=$2",
                json.dumps([{"split_node_id": str(target_id), "arm": chosen_arm}]),
                lead_id,
            )
            log.info(
                f"[sequencer] Split node {target_id}: arms={arms} → chose '{chosen_arm}' for lead {lead_id}"
            )
            await queue_next_nodes(lead_id, target_id, chosen_arm, accumulated_delay)

        elif node_type == "control_parallel_fork":
            # Fire all branches (up to 5) simultaneously
            log.info(f"[sequencer] Parallel fork {target_id} for lead {lead_id}")
            for i in range(1, 6):
                await queue_next_nodes(lead_id, target_id, f"branch_{i}", accumulated_delay)

        elif node_type == "control_race":
            # Like parallel_fork, but the first branch to advance (= produce a
            # downstream action receipt) wins and the others get cancelled by
            # the race_winners short-circuit at the top of queue_next_nodes.
            d = node.get("data") or {}
            try:
                branch_count = max(2, min(5, int(d.get("branch_count", 2))))
            except (TypeError, ValueError):
                branch_count = 2
            log.info(
                f"[sequencer] Race {target_id} (branches={branch_count}) for lead {lead_id}"
            )
            for i in range(1, branch_count + 1):
                await queue_next_nodes(lead_id, target_id, f"branch_{i}", accumulated_delay)

        elif node_type == "action_agent":
            # Hand-rolled Option C agent. Runs synchronously inside the sequencer
            # because tool calls already block on network; the loop is bounded by
            # max_turns + max_tokens so this can't spin away.
            from app.services.agent import run_agent

            d = node["data"] or {}
            goal = str(d.get("goal", "")).strip()
            toolset = d.get("tools") or []
            if not isinstance(toolset, list):
                toolset = []
            try:
                max_turns = int(d.get("max_turns", 10))
            except (TypeError, ValueError):
                max_turns = 10
            try:
                max_tokens = int(d.get("max_tokens", 10000))
            except (TypeError, ValueError):
                max_tokens = 10000

            if not goal or not toolset:
                log.warning(
                    f"[sequencer] action_agent {target_id} missing goal or toolset; routing to gave_up"
                )
                await queue_next_nodes(lead_id, target_id, "gave_up", accumulated_delay)
            else:
                _run_id, outcome = await run_agent(
                    lead_id=str(lead_id),
                    campaign_id=str(lead["campaign_id"]),
                    node_id=str(target_id),
                    goal=goal,
                    toolset=toolset,
                    max_turns=max_turns,
                    max_tokens=max_tokens,
                    default_email_account_id=d.get("default_email_account_id"),
                )
                log.info(
                    f"[sequencer] action_agent {target_id} lead={lead_id} outcome={outcome}"
                )
                await queue_next_nodes(lead_id, target_id, outcome, accumulated_delay)

        elif node_type == "event_webhook_received":
            # Park the lead until an external webhook hits /webhooks/events/wake
            # with this lead_id and node_id. No-op until then.
            await execute("UPDATE leads SET current_node_id=$1 WHERE id=$2", target_id, lead_id)
            log.info(
                f"[sequencer] Parking lead {lead_id} at event_webhook_received {target_id}"
            )

        elif node_type == "sticky_note":
            # Pure documentation node — no edges, no side effects. If something
            # somehow routes through here, just continue to default.
            await queue_next_nodes(lead_id, target_id, "default", accumulated_delay)

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
