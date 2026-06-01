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
from app.core.events import ChannelType
from app.db import close_pool, execute, fetch_one, init_pool, system_scope
from app.execution import commands
from app.services import bus

log = logging.getLogger("transitions")

TRANSITIONS_TOPIC = "outreach.transitions"
CONSUMER_GROUP = "v2-transitions"


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


async def _fan_out(workspace_id: str, parent: dict, for_each_node: dict, correlation_id: str | None) -> None:
    """A lead reached a flow.for_each node. Read the collection from the
    parent's custom_fields and spawn one child lead per element on the `each`
    edge. The parent parks (status='waiting') at the for_each node until the
    join barrier releases it. Empty collection -> walk done/empty immediately."""
    cfg = for_each_node.get("config") or {}
    items_key = cfg.get("items_key") or "items"
    item_field = cfg.get("item_field") or "item"
    max_items = int(cfg.get("max_items") or 500)
    for_each_id = str(for_each_node["id"])

    items = (parent.get("custom_fields") or {}).get(items_key) or []
    if not isinstance(items, list):
        items = []
    items = items[:max_items]

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


async def _join_arrive(workspace_id: str, child: dict, correlation_id: str | None) -> None:
    """A child lead reached a flow.join. End the child, bump the parent's
    fanout_done, and release the parent down the for_each `done` edge once all
    children have arrived (fanout_done == fanout_total)."""
    parent_id = child.get("parent_lead_id")
    origin_node_id = child.get("origin_node_id")
    await _advance_lead(workspace_id, str(child["id"]), None, status="completed")
    if not parent_id:
        return  # a join with no upstream for_each — child just ends

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

    ctx = noderegistry.NodeContext(
        workspace_id=workspace_id,
        workflow_id=str(node.get("workflow_id") or lead.get("workflow_id") or ""),
        node_id=str(node["id"]),
        config=node.get("config") or {},
        lead={
            **(contact or {}),
            "id": str(lead["id"]),
            "contact_id": lead.get("contact_id"),
            "custom_fields": lead.get("custom_fields") or {},
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

    # A condition/flow node has no muscle hop: it already chose a handle, so we
    # immediately emit a synthetic result for the orchestrator to transition on.
    if commands.NODE_CHANNEL.get(node_type) is None and result.events == []:
        await _emit_synthetic_result(workspace_id, str(lead["id"]), str(node["id"]), result.handle, correlation_id)


async def _emit_synthetic_result(workspace_id: str, lead_id: str, node_id: str, handle: str, correlation_id: str | None) -> None:
    """For non-muscle nodes, publish an ExecutionResult-shaped envelope to
    outreach.results so the Flink orchestrator emits the next transition."""
    result = {
        "command_id": str(uuid.uuid4()),
        "task_id": str(uuid.uuid4()),
        "lead_id": lead_id,
        "status": "skipped",  # ran to completion, no side effect
        "error": None,
        "is_retriable": False,
        "telemetry": {},
        "metadata": {
            "workspace_id": workspace_id,
            "node_id": node_id,
            "next_handle": handle,
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


async def handle_transition(t: dict) -> None:
    lead_id = t.get("lead_id")
    handle = t.get("handle") or "default"
    source_node_id = t.get("source_node_id")
    meta = t.get("metadata") or {}
    workspace_id = meta.get("workspace_id")
    correlation_id = meta.get("correlation_id")
    lead_mutations = meta.get("lead_mutations") or {}
    if not (lead_id and source_node_id):
        return
    if not workspace_id:
        # Fall back: read it off the lead.
        async with system_scope():
            row = await fetch_one("SELECT workspace_id FROM omni_leads WHERE id=$1", lead_id)
        workspace_id = str(row["workspace_id"]) if row else None
    if not workspace_id:
        log.warning("transition without workspace_id; lead=%s", lead_id)
        return

    # Apply any column mutations the muscle returned (e.g. a source handler
    # writing custom_fields[companies]) before deciding where to go next, so a
    # for_each or downstream node sees the freshly merged data.
    if lead_mutations:
        await _apply_lead_mutations(workspace_id, lead_id, lead_mutations)

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
        enable_auto_commit=True,
        auto_offset_reset="latest",
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
        while not stop.is_set():
            batch = await consumer.getmany(timeout_ms=1000, max_records=50)
            for _tp, records in batch.items():
                for rec in records:
                    try:
                        await handle_transition(rec.value)
                    except Exception:  # noqa: BLE001
                        log.exception("[transitions] failed to handle transition")
    finally:
        await consumer.stop()
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
