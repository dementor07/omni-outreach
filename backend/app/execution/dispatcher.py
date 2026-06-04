"""Dispatcher worker.

Consumes ``omni.events`` and turns a node's *intent* event into an
``ActionCommand`` on ``outreach.commands`` for the Rust muscle.

A node's ``execute`` emits an intent event like ``channel.email.queued`` or
``http_call.requested`` (payload carries the rendered request / connection
name). The dispatcher:

  1. recognises the intent event,
  2. looks up the lead + contact + the node's config from the canvas,
  3. resolves the ChannelType and mints a credential_ref,
  4. publishes the ActionCommand keyed by lead_id.

The muscle runs it and emits an ExecutionResult on ``outreach.results``; the
Flink orchestrator turns that into a transition (see transition_worker.py).

Intent-event shape (emitted by nodes, on omni.events):
  event_type: "<something>.queued" | "<something>.requested"
  entity_type: "lead" | "workflow"
  payload: {channel?, connection_name?, request?, correlation_id, ...}
  payload.node_id is set by the dispatcher's enroll path; for node-emitted
  intents we resolve node_id from the lead's current_node_id.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.core.events import ChannelType
from app.db import close_pool, fetch_one, init_pool, system_scope
from app.execution import commands
from app.services import bus

log = logging.getLogger("dispatcher")

EVENTS_TOPIC = "omni.events"
CONSUMER_GROUP = "v2-dispatcher"

# Intent events that should produce a muscle command.
_INTENT_SUFFIXES = (".queued", ".requested")


def _is_intent(event_type: str) -> bool:
    return event_type.endswith(_INTENT_SUFFIXES)


async def _resolve_node(workspace_id: str, node_id: str) -> dict | None:
    async with system_scope():
        return await fetch_one(
            "SELECT id, node_type, config FROM omni_workflow_nodes WHERE id=$1 AND workspace_id=$2",
            node_id,
            workspace_id,
        )


async def _resolve_lead_and_contact(workspace_id: str, lead_id: str) -> tuple[dict | None, dict | None]:
    async with system_scope():
        lead = await fetch_one(
            "SELECT * FROM omni_leads WHERE id=$1 AND workspace_id=$2", lead_id, workspace_id
        )
        contact = None
        if lead and lead.get("contact_id"):
            contact = await fetch_one(
                "SELECT * FROM omni_contacts WHERE id=$1 AND workspace_id=$2",
                lead["contact_id"],
                workspace_id,
            )
    return lead, contact


def _channel_for(node_type: str, payload: dict) -> ChannelType | None:
    # Declarative HTTP nodes announce themselves explicitly.
    if payload.get("channel") == "http_call":
        return ChannelType.HTTP_CALL
    return commands.NODE_CHANNEL.get(node_type)


async def handle_event(env: dict) -> None:
    event_type = env.get("event_type") or ""
    if not _is_intent(event_type):
        return
    workspace_id = env.get("workspace_id")
    payload = env.get("payload") or {}
    if not workspace_id:
        return

    # The node a lead sits on. For lead-scoped intents the entity is the lead;
    # node_id comes from payload (set when the dispatcher enrolled the lead) or
    # from the lead's current_node_id.
    lead_id = payload.get("lead_id") or (env.get("entity_id") if env.get("entity_type") == "lead" else None)
    node_id = payload.get("node_id")

    if not lead_id:
        # workflow-scoped source intent without a lead yet (e.g. a source node
        # that pulls leads). Route it as a node command keyed by workflow.
        node_id = node_id or payload.get("node_id")
        if not node_id:
            log.debug("intent %s without lead or node; skipping", event_type)
            return

    lead, contact = (None, None)
    if lead_id:
        lead, contact = await _resolve_lead_and_contact(workspace_id, lead_id)
        if lead and not node_id:
            node_id = str(lead.get("current_node_id") or "")
    if not node_id:
        log.debug("could not resolve node for intent %s", event_type)
        return

    node = await _resolve_node(workspace_id, node_id)
    if not node:
        log.warning("intent %s -> unknown node %s", event_type, node_id)
        return

    channel = _channel_for(node["node_type"], payload)
    if channel is None:
        # Not a muscle channel (condition/flow) — the orchestrator handles
        # advancement from the node's own handle; nothing to dispatch.
        log.debug("node %s (%s) is not a muscle channel; no command", node_id, node["node_type"])
        return

    # The command payload is whatever the node rendered (request for http_call;
    # rendered templates for channels) merged with the node's stored config.
    config = node.get("config") or {}
    command_payload = dict(config)
    command_payload.update({k: v for k, v in payload.items() if k not in ("node_id", "lead_id", "channel")})

    connection_name = payload.get("connection_name") or config.get("connection_name")

    synthetic_lead = lead or {"id": lead_id or str(node_id), "workflow_id": payload.get("workflow_id")}
    command = await commands.build_command(
        workspace_id=workspace_id,
        channel=channel,
        lead=synthetic_lead,
        contact=contact,
        node_id=str(node_id),
        payload=command_payload,
        connection_name=connection_name,
        correlation_id=payload.get("correlation_id") or env.get("correlation_id"),
    )
    await commands.publish_command(command)
    log.info("dispatched %s -> channel=%s node=%s", event_type, channel.value, node_id)


async def run() -> None:
    await init_pool(settings.database_url)
    await bus.init_producer()
    consumer = AIOKafkaConsumer(
        EVENTS_TOPIC,
        bootstrap_servers=settings.kafka_brokers,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        enable_auto_commit=True,
        auto_offset_reset="latest",
    )
    await consumer.start()
    log.info("[dispatcher] consuming %s", EVENTS_TOPIC)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await bus.consume_forever(consumer, handle_event, name="dispatcher", stop_event=stop)
    finally:
        await consumer.stop()
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
