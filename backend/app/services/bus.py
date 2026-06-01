"""Redpanda producer/consumer wrapper.

One module that every node and worker reaches for when publishing or
consuming events. Topics:

  omni.events       — the durable event log (source of truth)
  outreach.commands — muscle ActionCommands (in-flight, drops from log after ack)
  outreach.results  — muscle ExecutionResults (in-flight)

Workspace_id is always the partition key so per-tenant ordering holds.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from aiokafka import AIOKafkaProducer

from app.config import settings

log = logging.getLogger(__name__)

EVENTS_TOPIC = "omni.events"
COMMANDS_TOPIC = "outreach.commands"  # muscle ActionCommands (in-flight)
RESULTS_TOPIC = "outreach.results"  # muscle ExecutionResults (in-flight)
TRANSITIONS_TOPIC = "outreach.transitions"  # Flink orchestrator output

_producer: AIOKafkaProducer | None = None


async def init_producer() -> None:
    """Called by FastAPI lifespan + worker bootstrap."""
    global _producer
    if _producer is not None:
        return
    # gzip ships with the stdlib — no extra wheels. zstd needs python-zstandard
    # which would need adding to requirements.txt; gzip is fine until throughput
    # makes it the bottleneck.
    _producer = AIOKafkaProducer(
        bootstrap_servers=settings.kafka_brokers,
        value_serializer=lambda v: json.dumps(v, separators=(",", ":")).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if isinstance(k, str) else k,
        enable_idempotence=True,
        acks="all",
        compression_type="gzip",
    )
    await _producer.start()
    log.info("[bus] producer started, brokers=%s", settings.kafka_brokers)


async def close_producer() -> None:
    global _producer
    if _producer is not None:
        await _producer.stop()
        _producer = None


async def publish_event(
    *,
    workspace_id: str,
    event_type: str,
    entity_type: str,
    entity_id: str | None = None,
    payload: dict[str, Any] | None = None,
    actor_user_id: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Publish one event onto omni.events. Returns the envelope as published."""
    if _producer is None:
        raise RuntimeError("bus producer not initialised — call init_producer() first")
    envelope = {
        "id": str(uuid.uuid4()),
        "workspace_id": workspace_id,
        "event_type": event_type,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "payload": payload or {},
        "actor_user_id": actor_user_id,
        "correlation_id": correlation_id,
        "occurred_at": datetime.now(UTC).isoformat(),
    }
    await _producer.send_and_wait(EVENTS_TOPIC, value=envelope, key=workspace_id)
    return envelope


async def publish_events(envelopes: list[dict[str, Any]]) -> None:
    """Batch publish. All envelopes must already include workspace_id +
    event metadata in the same shape as ``publish_event`` returns."""
    if _producer is None:
        raise RuntimeError("bus producer not initialised")
    for env in envelopes:
        await _producer.send_and_wait(EVENTS_TOPIC, value=env, key=env["workspace_id"])


async def publish_command(command: dict[str, Any], *, key: str) -> None:
    """Publish an ActionCommand envelope onto outreach.commands. The muscle
    consumes this topic. `key` is the partition key (lead_id keeps a lead's
    commands ordered)."""
    if _producer is None:
        raise RuntimeError("bus producer not initialised")
    await _producer.send_and_wait(COMMANDS_TOPIC, value=command, key=key)

