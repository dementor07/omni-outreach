"""Transition worker.

Consumes ``outreach.transitions`` (emitted by the Flink orchestrator after the
muscle returns a result) and advances the lead through the canvas DAG:

  1. read the transition: (source_node_id, handle, lead_id)
  2. find the edge leaving source_node_id on that handle
  3. set the lead's current_node_id to the edge's target
  4. fire the target node by re-running its Python ``execute`` and publishing
     any intent events to omni.events (the dispatcher turns those into the
     next muscle command). Conditions/flow nodes resolve locally and emit
     their own transition so the DAG keeps moving without a muscle hop.

When no outgoing edge matches the handle, the lead has reached a leaf — mark it
completed.

Transition shape (StateTransition in app/core/events.py):
  {lead_id, campaign_id, source_node_id, handle, metadata:{workspace_id?,...}}
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import uuid
from datetime import UTC, datetime

from aiokafka import AIOKafkaConsumer

import app.nodes as noderegistry
from app.config import settings
from app.db import close_pool, execute, fetch_one, init_pool, system_scope
from app.execution import commands
from app.services import bus, company_kg

log = logging.getLogger("transitions")

TRANSITIONS_TOPIC = "outreach.transitions"
CONSUMER_GROUP = "v2-transitions"

# Recursion guards for flow.for_each. A single mis-wired loop edge can melt the
# system (see 2026-06 incident: one edge from a downstream join back into the
# for_each created a 113k-lead explosion). Two guards:
#   1. Ancestor walk — if any ancestor lead was spawned by THIS for_each node,
#      refuse to fan out again (the canvas has a cycle).
#   2. Per-root descendant cap — if the root parent's lineage already exceeds
#      MAX_DESCENDANTS_PER_ROOT, refuse further fan-out (runaway growth).
MAX_DESCENDANTS_PER_ROOT = 10_000
MAX_ANCESTOR_WALK_DEPTH = 64


async def _target_node(workspace_id: str, source_node_id: str, handle: str) -> dict | None:
    """Edge leaving source_node_id on `handle` -> the target node row."""
    async with system_scope():
        edge = await fetch_one(
            """
            SELECT target_node_id FROM omni_workflow_edges
            WHERE workspace_id=$1 AND source_node_id=$2 AND source_handle=$3
            LIMIT 1
            """,
            workspace_id,
            source_node_id,
            handle,
        )
        if not edge:
            return None
        return await fetch_one(
            "SELECT id, node_type, config, workflow_id FROM omni_workflow_nodes WHERE id=$1 AND workspace_id=$2",
            edge["target_node_id"],
            workspace_id,
        )


async def _advance_lead(workspace_id: str, lead_id: str, node_id: str | None, status: str = "active") -> None:
    async with system_scope():
        await execute(
            "UPDATE omni_leads SET current_node_id=$1, status=$2, updated_at=NOW() WHERE id=$3 AND workspace_id=$4",
            node_id,
            status,
            lead_id,
            workspace_id,
        )


async def _outgoing_edge(workspace_id: str, source_node_id: str, handle: str) -> dict | None:
    """The (target_node_id) edge leaving source_node_id on `handle`, or None."""
    async with system_scope():
        return await fetch_one(
            """
            SELECT target_node_id FROM omni_workflow_edges
            WHERE workspace_id=$1 AND source_node_id=$2 AND source_handle=$3
            LIMIT 1
            """,
            workspace_id,
            source_node_id,
            handle,
        )


async def _node_row(workspace_id: str, node_id: str) -> dict | None:
    async with system_scope():
        return await fetch_one(
            "SELECT id, node_type, config, workflow_id FROM omni_workflow_nodes WHERE id=$1 AND workspace_id=$2",
            node_id,
            workspace_id,
        )


async def _lead_with_contact(workspace_id: str, lead_id: str) -> tuple[dict | None, dict | None]:
    async with system_scope():
        lead = await fetch_one("SELECT * FROM omni_leads WHERE id=$1 AND workspace_id=$2", lead_id, workspace_id)
        contact = None
        if lead and lead.get("contact_id"):
            contact = await fetch_one(
                "SELECT * FROM omni_contacts WHERE id=$1 AND workspace_id=$2", lead["contact_id"], workspace_id
            )
    return lead, contact


async def _advance_and_fire(workspace_id: str, lead_id: str, target_node_id: str, correlation_id: str | None) -> None:
    """Move a lead to target_node_id and fire it — the normal advance path,
    reused by the for_each/join release so they don't duplicate it."""
    await _advance_lead(workspace_id, lead_id, target_node_id)
    node = await _node_row(workspace_id, target_node_id)
    lead, contact = await _lead_with_contact(workspace_id, lead_id)
    if lead and node:
        await _fire_node(workspace_id, lead, contact, node, correlation_id)


async def _ancestor_visited_for_each(
    workspace_id: str, parent: dict, for_each_id: str
) -> tuple[bool, str | None]:
    """Walk parent_lead_id upward; return (True, root_id) if any ancestor was
    spawned by THIS for_each node (cycle in the canvas wiring). Also returns
    the root parent_id (top of the chain) regardless, so callers can use it
    for the per-root descendant cap."""
    current_origin = parent.get("origin_node_id")
    if current_origin and str(current_origin) == for_each_id:
        return True, str(parent["id"])
    cur = parent
    root_id = str(parent["id"])
    for _ in range(MAX_ANCESTOR_WALK_DEPTH):
        parent_id = cur.get("parent_lead_id")
        if not parent_id:
            return False, root_id
        async with system_scope():
            cur = await fetch_one(
                "SELECT id, parent_lead_id, origin_node_id FROM omni_leads "
                "WHERE id=$1 AND workspace_id=$2",
                str(parent_id),
                workspace_id,
            )
        if not cur:
            return False, root_id
        root_id = str(cur["id"])
        if cur.get("origin_node_id") and str(cur["origin_node_id"]) == for_each_id:
            return True, root_id
    log.warning(
        "ancestor walk for lead %s exceeded depth %d — treating as cycle",
        parent.get("id"),
        MAX_ANCESTOR_WALK_DEPTH,
    )
    return True, root_id


async def _descendant_count_for_root(workspace_id: str, root_id: str) -> int:
    """Count total leads in the lineage rooted at root_id (recursive CTE).
    Used to enforce MAX_DESCENDANTS_PER_ROOT."""
    async with system_scope():
        row = await fetch_one(
            """
            WITH RECURSIVE lineage(id) AS (
                SELECT id FROM omni_leads WHERE id=$1 AND workspace_id=$2
                UNION ALL
                SELECT l.id FROM omni_leads l
                JOIN lineage ON l.parent_lead_id = lineage.id
                WHERE l.workspace_id=$2
            )
            SELECT count(*) AS n FROM lineage
            """,
            root_id,
            workspace_id,
        )
    return int((row or {}).get("n") or 0)


async def _fan_out(workspace_id: str, parent: dict, for_each_node: dict, correlation_id: str | None) -> None:
    """A lead reached a flow.for_each node. Read the collection from the
    parent's custom_fields and spawn one child lead per element on the `each`
    edge. The parent parks (status='waiting') at the for_each node until the
    join barrier releases it. Empty collection -> walk done/empty immediately.

    Refuses to fan out when the canvas has a cycle (an ancestor was spawned
    by this same for_each) or when the root lineage already exceeds the
    per-root descendant cap. In both cases the parent is routed down the
    done/empty edge so the workflow terminates cleanly instead of melting."""
    cfg = for_each_node.get("config") or {}
    items_key = cfg.get("items_key") or "items"
    item_field = cfg.get("item_field") or "item"
    # `or 500` would turn an explicit max_items=0 into 500 — a footgun when an
    # operator wants to disable a fan-out arm. Treat a missing/None value as
    # the default, but honour 0 (and any explicit int) literally.
    _raw_max = cfg.get("max_items")
    max_items = 500 if _raw_max is None else max(0, int(_raw_max))
    for_each_id = str(for_each_node["id"])

    # DEPLOY-001 idempotency: a redelivered transition (rebalance / replay) must
    # not double-spawn children. A parent that already fanned out at THIS node
    # is parked status='waiting' at current_node_id=for_each_id with a non-null
    # fanout_total. Detect that and no-op rather than spawning a second wave.
    if (
        str(parent.get("current_node_id") or "") == for_each_id
        and (parent.get("status") or "") == "waiting"
        and parent.get("fanout_total") is not None
    ):
        log.info("fan_out skipped: lead %s already fanned out at %s (redelivery)", parent.get("id"), for_each_id)
        return

    cycle_hit, root_id = await _ancestor_visited_for_each(workspace_id, parent, for_each_id)
    if cycle_hit:
        log.error(
            "fan_out refused: cycle detected at for_each=%s for lead=%s (root=%s)",
            for_each_id,
            parent.get("id"),
            root_id,
        )
        items = []
    else:
        descendants = await _descendant_count_for_root(workspace_id, root_id)
        if descendants >= MAX_DESCENDANTS_PER_ROOT:
            log.error(
                "fan_out refused: per-root descendant cap %d reached for root=%s at for_each=%s",
                MAX_DESCENDANTS_PER_ROOT,
                root_id,
                for_each_id,
            )
            items = []
        else:
            items = (parent.get("custom_fields") or {}).get(items_key) or []
            if not isinstance(items, list):
                items = []
            # E2E-001: defensively de-duplicate identical elements before the cap.
            # A source that returns the same company/person twice (or a replayed
            # mutation that appended a dup) must not spawn N identical children —
            # that wastes paid screens and inflates the join barrier. Dedup by a
            # stable JSON key, preserving first-seen order.
            items = _dedup_items(items)
            items = items[:max_items]
            # Cap each fan-out so a single rogue collection can't blow past
            # the per-root limit in one shot.
            remaining = MAX_DESCENDANTS_PER_ROOT - descendants
            if len(items) > remaining:
                log.warning(
                    "fan_out clamped: %d items -> %d to respect per-root cap (root=%s)",
                    len(items),
                    remaining,
                    root_id,
                )
                items = items[:remaining]

    each_edge = await _outgoing_edge(workspace_id, for_each_id, "each")
    if not items or not each_edge:
        done_edge = await _outgoing_edge(workspace_id, for_each_id, "done") or await _outgoing_edge(
            workspace_id, for_each_id, "empty"
        )
        if done_edge:
            await _advance_and_fire(workspace_id, str(parent["id"]), str(done_edge["target_node_id"]), correlation_id)
        else:
            await _advance_lead(workspace_id, str(parent["id"]), None, status="completed")
        return

    each_target = str(each_edge["target_node_id"])
    parent_id = str(parent["id"])

    async with system_scope():
        await execute(
            "UPDATE omni_leads SET current_node_id=$1, status='waiting', fanout_total=$2, "
            "fanout_done=0, updated_at=NOW() WHERE id=$3 AND workspace_id=$4",
            for_each_id,
            len(items),
            parent_id,
            workspace_id,
        )

    each_node = await _node_row(workspace_id, each_target)
    for element in items:
        child_id = str(uuid.uuid4())
        child_fields = dict(parent.get("custom_fields") or {})
        child_fields[item_field] = element
        async with system_scope():
            await execute(
                """
                INSERT INTO omni_leads
                    (id, workspace_id, contact_id, workflow_id, current_node_id, status,
                     custom_fields, parent_lead_id, origin_node_id)
                VALUES ($1, $2, $3, $4, $5, 'active', $6, $7, $8)
                """,
                child_id,
                workspace_id,
                parent.get("contact_id"),
                parent.get("workflow_id"),
                each_target,
                json.dumps(child_fields),
                parent_id,
                for_each_id,
            )
        child, contact = await _lead_with_contact(workspace_id, child_id)
        if child and each_node:
            await _fire_node(workspace_id, child, contact, each_node, correlation_id)

    log.info("fanned out lead %s -> %d children at %s", parent_id, len(items), for_each_id)


def _dedup_items(items: list) -> list:
    """Drop duplicate fan-out elements, preserving first-seen order. Keyed by a
    canonical JSON serialisation so dict elements (company/person rows) dedup by
    value. Non-serialisable elements fall back to identity (never dropped)."""
    seen: set[str] = set()
    out: list = []
    for el in items:
        try:
            key = json.dumps(el, sort_keys=True, default=str)
        except (TypeError, ValueError):
            out.append(el)
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append(el)
    return out


async def _outgoing_edges(workspace_id: str, source_node_id: str) -> list[dict]:
    """All edges leaving a node (source_handle + target_node_id). Used by race
    to spawn one child per branch arm."""
    async with system_scope():
        return await fetch_all(
            "SELECT source_handle, target_node_id FROM omni_workflow_edges "
            "WHERE workspace_id=$1 AND source_node_id=$2 ORDER BY source_handle",
            workspace_id,
            source_node_id,
        )


async def _race_fan_out(workspace_id: str, parent: dict, race_node: dict, correlation_id: str | None) -> None:
    """A lead reached flow.race. Spawn one child per ``branch_*`` edge leaving the
    race node; each child walks its arm in parallel. The parent parks
    (status='waiting', fanout_total=#arms). The FIRST child to reach the matching
    flow.join wins (see _join_arrive's race branch): the parent advances and the
    losing siblings are cancelled. Reuses the same lineage columns
    (parent_lead_id / origin_node_id) as for_each so the join machinery is shared.

    Idempotent on redelivery: a parent already parked at this race node with a
    non-null fanout_total has already fanned out — no-op."""
    race_id = str(race_node["id"])
    if (
        str(parent.get("current_node_id") or "") == race_id
        and (parent.get("status") or "") == "waiting"
        and parent.get("fanout_total") is not None
        and parent.get("fanout_total") > 0
    ):
        log.info("race_fan_out skipped: lead %s already raced at %s (redelivery)", parent.get("id"), race_id)
        return

    # Only the branch_* arms are race participants (the `timeout` handle is the
    # parent's own escape, not a child arm).
    arms = [
        e for e in await _outgoing_edges(workspace_id, race_id)
        if str(e["source_handle"]).startswith("branch_")
    ]
    if not arms:
        # Misconfigured race with no arms — route the parent to timeout (or leaf).
        timeout_edge = await _outgoing_edge(workspace_id, race_id, "timeout")
        if timeout_edge:
            await _advance_and_fire(workspace_id, str(parent["id"]), str(timeout_edge["target_node_id"]), correlation_id)
        else:
            await _advance_lead(workspace_id, str(parent["id"]), None, status="completed")
        log.warning("race %s has no branch_* arms; parent routed to timeout/leaf", race_id)
        return

    parent_id = str(parent["id"])
    async with system_scope():
        await execute(
            "UPDATE omni_leads SET current_node_id=$1, status='waiting', fanout_total=$2, "
            "fanout_done=0, updated_at=NOW() WHERE id=$3 AND workspace_id=$4",
            race_id,
            len(arms),
            parent_id,
            workspace_id,
        )

    for arm in arms:
        target_id = str(arm["target_node_id"])
        child_id = str(uuid.uuid4())
        child_fields = dict(parent.get("custom_fields") or {})
        async with system_scope():
            await execute(
                """
                INSERT INTO omni_leads
                    (id, workspace_id, contact_id, workflow_id, current_node_id, status,
                     custom_fields, parent_lead_id, origin_node_id)
                VALUES ($1, $2, $3, $4, $5, 'active', $6, $7, $8)
                """,
                child_id,
                workspace_id,
                parent.get("contact_id"),
                parent.get("workflow_id"),
                target_id,
                json.dumps(child_fields),
                parent_id,
                race_id,
            )
        child, contact = await _lead_with_contact(workspace_id, child_id)
        arm_node = await _node_row(workspace_id, target_id)
        if child and arm_node:
            await _fire_node(workspace_id, child, contact, arm_node, correlation_id)

    # Schedule the timeout: a delayed synthetic result for the PARENT on the
    # race's `timeout` handle. When it fires, handle_transition only honours it
    # if the parent is still parked at this race (no arm has won) — a winner
    # flips the parent to 'active'/advances it, so the late timeout no-ops.
    cfg = race_node.get("config") or {}
    timeout_hours = cfg.get("timeout_hours")
    timeout_hours = 168 if timeout_hours is None else int(timeout_hours)
    await _emit_synthetic_result(
        workspace_id, parent_id, race_id, "timeout", correlation_id,
        delay_seconds=float(timeout_hours) * 3600.0,
    )

    log.info("raced lead %s -> %d parallel arms at %s (timeout %dh)", parent_id, len(arms), race_id, timeout_hours)


async def _join_arrive(workspace_id: str, child: dict, correlation_id: str | None) -> None:
    """A child lead reached a flow.join. End the child, bump the parent's
    fanout_done, and release the parent down the for_each `done` edge once all
    children have arrived (fanout_done == fanout_total)."""
    parent_id = child.get("parent_lead_id")
    origin_node_id = child.get("origin_node_id")
    # JOIN-IDEMPOTENCY (E2E-001): end the child atomically and gate everything
    # below on whether THIS call is the one that completed it. Kafka is
    # at-least-once, so the same child's join-arrival transition can be
    # redelivered; without this guard each redelivery bumped the parent's
    # fanout_done again (observed fanout_done=64 against fanout_total=1),
    # releasing the barrier early and tearing the parent down to flow.end before
    # the real children finished. Counting DISTINCT children (one increment per
    # child, ever) is the correct barrier semantics.
    async with system_scope():
        claimed = await fetch_one(
            "UPDATE omni_leads SET current_node_id=NULL, status='completed', updated_at=NOW() "
            "WHERE id=$1 AND workspace_id=$2 AND status<>'completed' RETURNING id",
            str(child["id"]),
            workspace_id,
        )
    if not claimed:
        return  # this child already arrived + was counted — redelivery no-op
    if not parent_id:
        return  # a join with no upstream for_each/race — child just ends

    # The origin node decides the barrier semantics: flow.race releases on the
    # FIRST arrival (and cancels the losers); flow.for_each waits for ALL.
    origin = await _node_row(workspace_id, str(origin_node_id)) if origin_node_id else None
    origin_type = (origin or {}).get("node_type")

    if origin_type == "flow.race":
        # First-arm-wins. Atomically claim the win: only the first arrival flips
        # the parent out of 'waiting'. RETURNING gates the race so a second
        # arriving sibling sees no row and no-ops (idempotent under redelivery).
        async with system_scope():
            parent = await fetch_one(
                "UPDATE omni_leads SET status='active', fanout_done = fanout_done + 1, "
                "updated_at=NOW() WHERE id=$1 AND workspace_id=$2 AND status='waiting' RETURNING *",
                str(parent_id),
                workspace_id,
            )
        if not parent:
            return  # a sibling already won (or parent gone) — this loser just ended above
        # Cancel the still-running losing siblings (other children of this race).
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET status='cancelled', current_node_id=NULL, updated_at=NOW() "
                "WHERE workspace_id=$1 AND parent_lead_id=$2 AND origin_node_id=$3 "
                "AND id<>$4 AND status NOT IN ('completed','cancelled')",
                workspace_id,
                str(parent_id),
                str(origin_node_id),
                str(child["id"]),
            )
        done_edge = await _outgoing_edge(workspace_id, str(origin_node_id), "done")
        if not done_edge:
            await _advance_lead(workspace_id, str(parent["id"]), None, status="completed")
            log.info("race won by %s; parent %s released (no done edge) -> completed", child["id"], parent["id"])
            return
        await _advance_and_fire(workspace_id, str(parent["id"]), str(done_edge["target_node_id"]), correlation_id)
        log.info("race won by %s; parent %s -> %s, siblings cancelled", child["id"], parent["id"], done_edge["target_node_id"])
        return

    # flow.for_each barrier: wait for ALL children.
    async with system_scope():
        parent = await fetch_one(
            "UPDATE omni_leads SET fanout_done = fanout_done + 1, updated_at=NOW() "
            "WHERE id=$1 AND workspace_id=$2 RETURNING *",
            str(parent_id),
            workspace_id,
        )
    if not parent or (parent.get("fanout_done") or 0) < (parent.get("fanout_total") or 0):
        return  # barrier not yet satisfied (or parent gone)

    done_edge = await _outgoing_edge(workspace_id, str(origin_node_id), "done")
    if not done_edge:
        await _advance_lead(workspace_id, str(parent["id"]), None, status="completed")
        log.info("join released parent %s (no done edge) -> completed", parent["id"])
        return
    await _advance_and_fire(workspace_id, str(parent["id"]), str(done_edge["target_node_id"]), correlation_id)
    log.info("join released parent %s -> %s", parent["id"], done_edge["target_node_id"])


# Fixed-duration unit table for flow.delay (mirrors the node's own table).
_DELAY_UNIT_SECONDS = {"minutes": 60, "hours": 3600, "days": 86400}


async def _workflow_timezone(workspace_id: str, workflow_id: str | None) -> str:
    if not workflow_id:
        return "UTC"
    async with system_scope():
        row = await fetch_one(
            "SELECT timezone FROM omni_workflows WHERE id=$1 AND workspace_id=$2",
            workflow_id,
            workspace_id,
        )
    return (row or {}).get("timezone") or "UTC"


async def _compute_flow_delay_seconds(workspace_id: str, node: dict) -> float:
    """Seconds a flow.delay / flow.wait_until node should hold the lead.

    flow.delay: amount × unit (fixed duration).
    flow.wait_until: seconds until the next moment inside the configured
    business-hours window (earliest_hour ≤ local hour < latest_hour, on an
    allowed weekday), evaluated in the workflow's timezone. 0 if the window is
    open right now."""
    from datetime import datetime, timedelta
    from zoneinfo import ZoneInfo

    cfg = node.get("config") or {}
    node_type = node.get("node_type")

    if node_type == "flow.delay":
        amount = int(cfg.get("amount") or 0)
        unit = cfg.get("unit") or "hours"
        return float(max(0, amount) * _DELAY_UNIT_SECONDS.get(unit, 3600))

    # flow.wait_until
    earliest = int(cfg.get("earliest_hour", 9))
    latest = int(cfg.get("latest_hour", 17))
    days = cfg.get("days_of_week") or [0, 1, 2, 3, 4]
    try:
        tz = ZoneInfo(await _workflow_timezone(workspace_id, node.get("workflow_id")))
    except Exception:  # noqa: BLE001 — bad tz string → UTC
        tz = ZoneInfo("UTC")
    now = datetime.now(tz)
    # Search forward up to 8 days for the first minute the window is open.
    for day_offset in range(0, 8):
        d = now + timedelta(days=day_offset)
        if d.weekday() not in days:
            continue
        window_open = d.replace(hour=earliest, minute=0, second=0, microsecond=0)
        window_close = d.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(hours=latest)
        if day_offset == 0 and now >= window_open and now < window_close:
            return 0.0  # already inside the window
        if d >= now and window_open >= now:
            return max(0.0, (window_open - now).total_seconds())
    return 0.0  # no matching day found in a week → don't hold


# Intent-event suffixes the dispatcher recognises (must match dispatcher._is_intent).
_INTENT_SUFFIXES = (".queued", ".requested")


def _is_intent_event(event_type: str) -> bool:
    return bool(event_type) and event_type.endswith(_INTENT_SUFFIXES)


def _classify_emitted_events(events: list[dict]) -> str:
    """Classify what a non-muscle node's emitted events mean for advancement:

      'projection_only' — no intent events; the events are facts for the
          projector (e.g. contact.tag_added). The lead should advance locally
          via a synthetic result, exactly like a condition/flow node.
      'routable_intent' — every intent event is dispatcher-routable (carries
          channel=='http_call'; the only route left for a non-muscle node). The
          muscle result will drive the next transition; do nothing here.
      'dead_on_arrival' — emits an intent the dispatcher can't route. The lead
          would stall silently (CONTRACT-001) — caller errors it instead.
    """
    intents = [e for e in events if _is_intent_event(e.get("event_type") or "")]
    if not intents:
        return "projection_only"
    if all((e.get("payload") or {}).get("channel") == "http_call" for e in intents):
        return "routable_intent"
    return "dead_on_arrival"


async def _fire_node(workspace_id: str, lead: dict, contact: dict | None, node: dict, correlation_id: str | None) -> None:
    """Run the target node's execute() and route its output.

    Side-effecting nodes emit intent events -> dispatcher -> muscle.
    Condition/flow nodes return a handle with no muscle hop -> we publish a
    synthetic result so the orchestrator emits the next transition.
    """
    node_type = node["node_type"]
    try:
        _manifest, execute_fn = noderegistry.get(node_type)
    except KeyError:
        log.warning("target node type %r not in registry; stopping lead", node_type)
        await _advance_lead(workspace_id, str(lead["id"]), None, status="errored")
        return

    # CONTRACT-006: surface the contact's most recent inbound (reply) timestamp
    # so condition.replied can evaluate against real data. The node itself has no
    # DB handle — the worker is the place with one (same pattern as has_tag
    # reading custom_fields.tags). Cheap single-row lookup, only when needed.
    last_inbound_at = None
    if node_type == "condition.replied" and lead.get("contact_id"):
        # CMP8: honour the node's optional `channel` filter — "did they reply on
        # email specifically?" must not match a LinkedIn reply. The node has no DB
        # handle, so the worker reads its config and filters the query.
        replied_channel = (node.get("config") or {}).get("channel")
        async with system_scope():
            if replied_channel:
                row = await fetch_one(
                    "SELECT MAX(occurred_at) AS last_inbound FROM omni_messages "
                    "WHERE workspace_id=$1 AND contact_id=$2 AND direction='inbound' AND channel=$3",
                    workspace_id,
                    lead["contact_id"],
                    replied_channel,
                )
            else:
                row = await fetch_one(
                    "SELECT MAX(occurred_at) AS last_inbound FROM omni_messages "
                    "WHERE workspace_id=$1 AND contact_id=$2 AND direction='inbound'",
                    workspace_id,
                    lead["contact_id"],
                )
        last_inbound_at = (row or {}).get("last_inbound")

    # Company knowledge-graph resolution for crm.resolve_company. The node has no
    # DB handle, so the worker resolves+dedups the company here and injects the
    # result into custom_fields.company_resolution (same pattern as replied).
    node_custom_fields = dict(lead.get("custom_fields") or {})
    if node_type == "crm.resolve_company":
        cfg = node.get("config") or {}
        item_field = cfg.get("item_field") or "item"
        company_row = node_custom_fields.get(item_field) or {}
        raw_name = (company_row.get("company_name") or "").strip()
        if raw_name:
            description = company_row.get("description") or ""
            industry = company_row.get("industry") or company_row.get("sector") or ""
            employee_count = company_row.get("employee_count")
            async with system_scope():
                resolved = await company_kg.resolve_company(
                    workspace_id,
                    raw_name,
                    industry=industry or None,
                    employee_count=employee_count,
                    domain=company_row.get("company_url") or None,
                )
                # Local filter (blocklist / employee cap / enterprise / org type).
                passed, reason = await company_kg.filter_company(
                    workspace_id,
                    resolved.name,
                    description=description,
                    industry=industry,
                    employee_count=employee_count,
                )
                if not passed and resolved.screening_status != "rejected":
                    await company_kg.set_screening_status(workspace_id, resolved.id, "rejected")
                # Signal scoring from this job's title/description.
                title = company_row.get("title") or company_row.get("job_title") or ""
                role_count = int(company_row.get("role_count") or 1)
                total, signals = company_kg.score_signals(title, description, role_count=role_count)
                if signals:
                    await company_kg.persist_signals(workspace_id, resolved.id, signals, "naukri")
            node_custom_fields["company_resolution"] = {
                "company_id": resolved.id,
                "name": resolved.name,
                "screening_status": "rejected" if not passed else resolved.screening_status,
                "people_discovered": resolved.people_discovered,
                "created": resolved.created,
                "filter_passed": passed,
                "filter_reason": reason,
                "signal_score": total,
            }

    ctx = noderegistry.NodeContext(
        workspace_id=workspace_id,
        workflow_id=str(node.get("workflow_id") or lead.get("workflow_id") or ""),
        node_id=str(node["id"]),
        config=node.get("config") or {},
        lead={
            **(contact or {}),
            "id": str(lead["id"]),
            "contact_id": lead.get("contact_id"),
            "custom_fields": node_custom_fields,
            "last_inbound_at": last_inbound_at.isoformat() if last_inbound_at else None,
        },
        correlation_id=correlation_id,
    )
    result = await execute_fn(ctx)

    # Publish any intent events the node emitted (channels/sources/http_call).
    if result.events:
        envelopes = []
        for ev in result.events:
            payload = dict(ev.get("payload") or {})
            payload.setdefault("node_id", str(node["id"]))
            payload.setdefault("lead_id", str(lead["id"]))
            envelopes.append(
                {
                    "id": str(uuid.uuid4()),
                    "workspace_id": workspace_id,
                    "event_type": ev["event_type"],
                    "entity_type": ev.get("entity_type", "lead"),
                    "entity_id": ev.get("entity_id") or str(lead["id"]),
                    "payload": payload,
                    "actor_user_id": None,
                    "correlation_id": correlation_id,
                    "occurred_at": datetime.now(UTC).isoformat(),
                }
            )
        await bus.publish_events(envelopes)

    # M3: accrue the company knowledge-graph people cache. When a person reaches
    # crm.create_contact inside the people fan-out, the lead carries the person
    # (custom_fields.item) and the resolved company (custom_fields.company_resolution).
    # Cache the person against that company and mark the company people-discovered,
    # so a future run hits crm.resolve_company's `known` branch and skips paid
    # re-discovery (the KG moat that was previously inert — cache_person had no
    # caller). The node has no DB handle, so the worker does it (same pattern as
    # the resolve_company injection above).
    if node_type == "crm.create_contact" and not result.error:
        person = node_custom_fields.get("item") or {}
        resolution = node_custom_fields.get("company_resolution") or {}
        company_id = resolution.get("company_id")
        linkedin_url = person.get("linkedin_url") or (contact or {}).get("linkedin_url")
        if company_id and linkedin_url:
            person_name = " ".join(
                p for p in (person.get("first_name"), person.get("last_name")) if p
            ).strip() or person.get("name") or ""
            async with system_scope():
                await company_kg.cache_person(
                    workspace_id,
                    str(company_id),
                    name=person_name,
                    title=person.get("title") or person.get("headline"),
                    linkedin_url=str(linkedin_url),
                    source=person.get("source") or "discovery",
                )
                await company_kg.mark_people_discovered(workspace_id, str(company_id))
            log.info("KG: cached person for company %s (people_discovered=true)", company_id)

    # CONTRACT-005: a node that parks (flow.human_approval) suspends the lead.
    # Its events were published above (approval.requested -> approvals queue);
    # the lead now WAITS and must not advance. It resumes when the resolve
    # endpoint emits approval.resolved, which arrives as a transition off this
    # node's chosen handle.
    if result.park:
        await _advance_lead(workspace_id, str(lead["id"]), str(node["id"]), status="waiting")
        log.info("lead %s parked at %s (%s)", lead["id"], node["id"], node_type)
        return

    # Decide how the lead advances past this node:
    #   * muscle channel (node_type in NODE_CHANNEL) → a command was/will be
    #     dispatched off the intent event; the muscle's result drives the next
    #     transition. Nothing to do here.
    #   * non-muscle node → classify its emitted events:
    #       - projection_only (no intents, or none at all): a condition/flow
    #         node that chose a handle, or a CRM mutation that emitted facts for
    #         the projector (e.g. contact.tag_added). Advance locally via a
    #         synthetic result.
    #       - routable_intent: every intent is dispatcher-routable (http_call);
    #         the muscle result drives the next transition. Do nothing.
    #       - dead_on_arrival: an intent the dispatcher can't route. The lead
    #         would stall silently (CONTRACT-001). Make it LOUD — error the lead.
    if commands.NODE_CHANNEL.get(node_type) is not None:
        return
    # H1: flow.goal / flow.end are TERMINAL — the lead exits here. Set a distinct
    # terminal status (converted vs ended) directly so a goal-conversion is
    # distinguishable from a dead-end in the Leads view + Analytics, instead of
    # both collapsing to the generic 'completed' the leaf path would assign. No
    # synthetic result is emitted (there is no outgoing edge to follow).
    if node_type in ("flow.goal", "flow.end"):
        terminal_status = "converted" if node_type == "flow.goal" else "ended"
        await _advance_lead(workspace_id, str(lead["id"]), None, status=terminal_status)
        log.info("lead %s reached %s -> status=%s", lead["id"], node_type, terminal_status)
        return
    # CMP9/CMP10: flow.delay / flow.wait_until must actually HOLD the lead. They
    # advance on the same handle as a projection-only node, but with a non-zero
    # delay so the orchestrator's processing-time timer fires the transition
    # later (the mechanism flow.race's timeout uses). Without this they emitted
    # delay only as telemetry and advanced immediately — a "wait 3 days" fired
    # instantly. The lead parks 'waiting' until the timer releases it.
    if node_type in ("flow.delay", "flow.wait_until"):
        delay_seconds = await _compute_flow_delay_seconds(workspace_id, node)
        if delay_seconds > 0:
            await _advance_lead(workspace_id, str(lead["id"]), str(node["id"]), status="waiting")
        await _emit_synthetic_result(
            workspace_id, str(lead["id"]), str(node["id"]), result.handle, correlation_id,
            delay_seconds=delay_seconds,
        )
        log.info("lead %s holding at %s for %.0fs", lead["id"], node_type, delay_seconds)
        return
    kind = _classify_emitted_events(result.events)
    if kind == "projection_only":
        await _emit_synthetic_result(workspace_id, str(lead["id"]), str(node["id"]), result.handle, correlation_id)
    elif kind == "dead_on_arrival":
        log.error(
            "node %s (%s) emitted unroutable intent event(s) %s — no muscle channel/handler; "
            "marking lead %s errored instead of stalling silently (CONTRACT-001)",
            node["id"],
            node_type,
            [e.get("event_type") for e in result.events],
            lead["id"],
        )
        await _advance_lead(workspace_id, str(lead["id"]), None, status="errored")


async def _emit_synthetic_result(
    workspace_id: str,
    lead_id: str,
    node_id: str,
    handle: str,
    correlation_id: str | None,
    delay_seconds: float = 0.0,
) -> None:
    """For non-muscle nodes, publish an ExecutionResult-shaped envelope to
    outreach.results so the Flink orchestrator emits the next transition.

    ``delay_seconds`` > 0 schedules the transition for later via the
    orchestrator's processing-time timer (the same mechanism flow.delay uses).
    The orchestrator only delays ``sent`` results, so a delayed synthetic uses
    status='sent'; an immediate one uses 'skipped' (ran, no side effect)."""
    result = {
        "command_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "lead_id": lead_id,
        "status": "sent" if delay_seconds > 0 else "skipped",
        "error": None,
        "is_retriable": False,
        "telemetry": {},
        "metadata": {
            "workspace_id": workspace_id,
            "node_id": node_id,
            "next_handle": handle,
            "accumulated_delay_seconds": delay_seconds,
            # DATAFLOW-001: carry the run identity forward. Without this the
            # orchestrator emits the next transition with correlation_id=None and
            # the downstream node mints a fresh id (`ctx.correlation_id or uuid4`),
            # forking the trace at every condition/flow/synthetic hop.
            "correlation_id": correlation_id,
        },
        "event_type": "result_task",
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    # publish to outreach.results via the raw producer
    await bus._producer.send_and_wait(bus.RESULTS_TOPIC, value=result, key=lead_id)  # type: ignore[union-attr]


async def _apply_lead_mutations(workspace_id: str, lead_id: str, mutations: dict) -> None:
    """Merge muscle-supplied column mutations into omni_leads.

    Only ``custom_fields`` (jsonb merge) is supported today — that's how source
    handlers (Apify, Serper) hand a fanned-out collection to the next
    ``flow.for_each``. Other top-level lead columns can be wired here as
    explicit branches; we don't blindly UPDATE arbitrary columns because the
    muscle is not trusted to name internal DB schema."""
    if not mutations:
        return
    cf = mutations.get("custom_fields")
    if isinstance(cf, dict) and cf:
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET custom_fields = COALESCE(custom_fields,'{}'::jsonb) || $1::jsonb, "
                "updated_at = NOW() WHERE id=$2 AND workspace_id=$3",
                json.dumps(cf),
                lead_id,
                workspace_id,
            )

    # CONTRACT-003: persist tag mutations into custom_fields.tags (a JSONB string
    # array). condition.has_tag reads the same location. The ADD_TAG/REMOVE_TAG
    # muscle handlers return lead_mutations.{add_tag|remove_tag: <tag>}; apply
    # them set-wise so re-delivery is idempotent.
    add_tag = mutations.get("add_tag")
    remove_tag = mutations.get("remove_tag")
    if isinstance(add_tag, str) and add_tag:
        async with system_scope():
            await execute(
                """
                UPDATE omni_leads SET custom_fields = jsonb_set(
                    COALESCE(custom_fields,'{}'::jsonb), '{tags}',
                    (
                        SELECT COALESCE(jsonb_agg(DISTINCT t), '[]'::jsonb)
                        FROM jsonb_array_elements_text(
                            COALESCE(custom_fields->'tags','[]'::jsonb) || to_jsonb($1::text)
                        ) AS t
                    ), true
                ), updated_at = NOW()
                WHERE id=$2 AND workspace_id=$3
                """,
                add_tag,
                lead_id,
                workspace_id,
            )
    if isinstance(remove_tag, str) and remove_tag:
        async with system_scope():
            await execute(
                """
                UPDATE omni_leads SET custom_fields = jsonb_set(
                    COALESCE(custom_fields,'{}'::jsonb), '{tags}',
                    (
                        SELECT COALESCE(jsonb_agg(t), '[]'::jsonb)
                        FROM jsonb_array_elements_text(COALESCE(custom_fields->'tags','[]'::jsonb)) AS t
                        WHERE t <> $1::text
                    ), true
                ), updated_at = NOW()
                WHERE id=$2 AND workspace_id=$3
                """,
                remove_tag,
                lead_id,
                workspace_id,
            )


async def handle_transition(t: dict) -> None:
    lead_id = t.get("lead_id")
    handle = t.get("handle") or "default"
    source_node_id = t.get("source_node_id")
    meta = t.get("metadata") or {}
    echoed_workspace_id = meta.get("workspace_id")
    correlation_id = meta.get("correlation_id")
    lead_mutations = meta.get("lead_mutations") or {}
    if not (lead_id and source_node_id):
        return

    # DATAFLOW-003: the muscle echoes workspace_id through its metadata, but the
    # muscle is not trusted to assert tenancy. The lead row is the source of
    # truth — derive workspace_id from it by lead_id, and only trust the echoed
    # value as a cross-check. A mismatch means a tenancy bug or a tampered
    # result; refuse the transition rather than acting in the echoed tenant.
    async with system_scope():
        row = await fetch_one("SELECT workspace_id FROM omni_leads WHERE id=$1", lead_id)
    workspace_id = str(row["workspace_id"]) if row else None
    if not workspace_id:
        log.warning("transition for unknown lead=%s; dropping", lead_id)
        return
    if echoed_workspace_id and str(echoed_workspace_id) != workspace_id:
        log.error(
            "transition workspace mismatch: lead=%s echoed=%s actual=%s — refusing",
            lead_id,
            echoed_workspace_id,
            workspace_id,
        )
        return

    # Apply any column mutations the muscle returned (e.g. a source handler
    # writing custom_fields[companies]) before deciding where to go next, so a
    # for_each or downstream node sees the freshly merged data.
    if lead_mutations:
        await _apply_lead_mutations(workspace_id, lead_id, lead_mutations)

    # FLINK-001: the orchestrator emits handle="__retry__" after a retriable
    # failure's backoff timer fires. This is NOT an edge — re-fire the SAME node
    # the lead failed on (source_node_id) so the command is genuinely redriven.
    if handle == "__retry__":
        node = await _node_row(workspace_id, source_node_id)
        lead, contact = await _lead_with_contact(workspace_id, lead_id)
        if node and lead:
            log.info("redriving lead %s at node %s (retry)", lead_id, source_node_id)
            await _fire_node(workspace_id, lead, contact, node, correlation_id)
        else:
            log.warning("retry for lead %s: node/lead gone; dropping", lead_id)
        return

    # flow.race timeout: the delayed timeout transition only fires the `timeout`
    # arm if the parent is STILL parked at the race (no arm won). A winner already
    # flipped the parent to 'active' and advanced it, so a late timeout is a stale
    # no-op. Also cancel any still-running arms when the timeout actually fires.
    if handle == "timeout":
        async with system_scope():
            prow = await fetch_one(
                "SELECT status, current_node_id FROM omni_leads WHERE id=$1 AND workspace_id=$2",
                lead_id,
                workspace_id,
            )
        still_waiting = (
            prow
            and (prow.get("status") or "") == "waiting"
            and str(prow.get("current_node_id") or "") == str(source_node_id)
        )
        if not still_waiting:
            log.info("race timeout for lead %s ignored — already resolved", lead_id)
            return
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET status='cancelled', current_node_id=NULL, updated_at=NOW() "
                "WHERE workspace_id=$1 AND parent_lead_id=$2 AND origin_node_id=$3 "
                "AND status NOT IN ('completed','cancelled')",
                workspace_id,
                lead_id,
                str(source_node_id),
            )
        await _advance_lead(workspace_id, lead_id, None, status="active")

    target = await _target_node(workspace_id, source_node_id, handle)
    if not target:
        # Leaf reached on this handle — the lead's journey is done.
        await _advance_lead(workspace_id, lead_id, None, status="completed")
        log.info("lead %s reached leaf at node %s/%s", lead_id, source_node_id, handle)
        return

    target_type = target["node_type"]

    # flow.join: a child arriving at the barrier is handled before any normal
    # advance — it ends the child and may release the parent. We resolve the
    # arriving lead's lineage first.
    if target_type == "flow.join":
        lead, _contact = await _lead_with_contact(workspace_id, lead_id)
        if lead:
            await _join_arrive(workspace_id, lead, correlation_id)
            log.info("lead %s arrived at join %s", lead_id, target["id"])
        return

    await _advance_lead(workspace_id, lead_id, str(target["id"]))
    lead, contact = await _lead_with_contact(workspace_id, lead_id)
    if not lead:
        return

    # flow.for_each: interior fan-out. Don't fire it as an ordinary node —
    # spawn one child lead per element of the parent's collection.
    if target_type == "flow.for_each":
        await _fan_out(workspace_id, lead, target, correlation_id)
        return

    # flow.race: parallel fan-out. Spawn one child per branch_N edge; the parent
    # parks until the FIRST child re-converges at a flow.join (first-arm-wins).
    if target_type == "flow.race":
        await _race_fan_out(workspace_id, lead, target, correlation_id)
        return

    await _fire_node(workspace_id, lead, contact, target, correlation_id)
    log.info("advanced lead %s -> node %s (%s)", lead_id, target["id"], target_type)


async def run() -> None:
    await init_pool(settings.database_url)
    await bus.init_producer()
    noderegistry.discover()
    consumer = AIOKafkaConsumer(
        TRANSITIONS_TOPIC,
        bootstrap_servers=settings.kafka_brokers,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        # DEPLOY-001: manual commit-after-success (commit=True below). A timer
        # auto-commit could advance the offset mid-handle, dropping a transition
        # on crash; or redeliver after a rebalance and re-run _fan_out, double-
        # spawning children. We commit only after handle_transition returns, and
        # _fan_out is now idempotent on (parent, for_each_node). Keep replicas:1.
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    log.info("[transitions] consuming %s", TRANSITIONS_TOPIC)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await bus.consume_forever(consumer, handle_transition, name="transitions", stop_event=stop, commit=True)
    finally:
        await consumer.stop()
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
