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
DEAD_LETTER_TOPIC = "outreach.dead_letter"  # poison records that exhausted handling

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


async def publish_dead_letter(
    *, worker: str, original: Any, error: str, topic: str, partition: int, offset: int
) -> None:
    """Park a record that failed handling onto the dead-letter topic so the
    offset can advance without losing the payload. Best-effort: if the producer
    itself is down we log and let the caller decide whether to advance."""
    if _producer is None:
        raise RuntimeError("bus producer not initialised")
    envelope = {
        "worker": worker,
        "error": error,
        "source_topic": topic,
        "source_partition": partition,
        "source_offset": offset,
        "original": original,
        "dead_lettered_at": datetime.now(UTC).isoformat(),
    }
    await _producer.send_and_wait(DEAD_LETTER_TOPIC, value=envelope, key=worker)


# ── Defensive consume loop ────────────────────────────────────────────────
# A consumer must never be killed by a single bad batch. Two failure classes:
#
#   1. Decode/codec failure — a producer wrote the batch in a compression codec
#      this consumer's aiokafka doesn't have a library for (e.g. an operator
#      using `rpk produce`, whose default is snappy). The error is raised
#      *inside* the fetch/iteration, before any record surfaces, so a naive
#      `for rec in consumer: try: ...` does NOT catch it — the loop dies and
#      the container crash-loops on the same poison offset forever.
#
#   2. Handler failure — our own code threw on one record. That one we log and
#      skip; the rest of the batch is fine.
#
# `consume_forever` guards both. On a fetch-level error it logs loudly and
# skips the batch by advancing each assigned partition past its current
# position, so one undecodable message can't wedge the whole worker. Real
# traffic uses gzip (see init_producer) which always decodes; the codec libs
# in requirements cover snappy/lz4/zstd; this guard covers the unknown.

from aiokafka import AIOKafkaConsumer  # noqa: E402


async def _skip_current_batch(consumer: AIOKafkaConsumer) -> None:
    """Step every assigned partition PAST the entire poison batch.

    A codec/decode failure is raised for the whole fetched batch before any
    record surfaces, so we don't know which offsets it spanned. Seeking to the
    partition's high-watermark (end) steps past all of it in one move; advancing
    a single offset (the old ``pos + 1``) would re-fetch and re-fail the same
    batch on the next poll (EXEC-002)."""
    assignment = list(consumer.assignment())
    if not assignment:
        return
    try:
        end_offsets = await consumer.end_offsets(assignment)
    except Exception:  # noqa: BLE001
        end_offsets = {}
    for tp in assignment:
        try:
            target = end_offsets.get(tp)
            if target is None:
                target = await consumer.position(tp) + 1
            consumer.seek(tp, target)
            log.warning("[bus] skipped poison batch on %s -> offset %s", tp, target)
        except Exception:  # noqa: BLE001
            log.exception("[bus] failed to skip batch on %s", tp)


async def consume_forever(
    consumer: AIOKafkaConsumer,
    handler,  # async callable(record_value) -> None
    *,
    name: str,
    stop_event=None,
    commit: bool = False,
    on_record=None,  # optional async callable(rec) for manual commit/offset bookkeeping
) -> None:
    """Run a crash-tolerant consume loop.

    Failure policy (RETRY-THEME / EXEC-001):
      - fetch errors (codec/decode) → log + skip the whole poison batch, never crash
      - handler error with ``commit=True`` → dead-letter the record, then advance
        past it (at-least-once with a poison escape hatch). The offset is only
        committed AFTER the record was either handled or dead-lettered, so a
        crash mid-handle redelivers the record instead of dropping it.
      - handler error with ``commit=False`` (auto-commit consumers / the
        projector, which commits inside ``on_record``) → log + skip the record.
      - clean shutdown when stop_event is set.

    ``commit`` consumers MUST be created with ``enable_auto_commit=False`` so the
    only commits are the deliberate after-success ones below.
    """
    while stop_event is None or not stop_event.is_set():
        try:
            batch = await consumer.getmany(timeout_ms=1000, max_records=50)
        except Exception as e:  # noqa: BLE001 — fetch-level (incl. codec) failures (EXEC-004)
            log.exception("[%s] fetch failed (%s); skipping poison batch", name, type(e).__name__)
            await _skip_current_batch(consumer)
            continue
        for _tp, records in batch.items():
            for rec in records:
                handled = False
                try:
                    await handler(rec.value)
                    if on_record is not None:
                        await on_record(rec)
                    handled = True
                except Exception:  # noqa: BLE001 — never kill the loop on one record
                    log.exception("[%s] failed to handle record offset=%s", name, getattr(rec, "offset", "?"))
                    if commit:
                        # Park the poison record so advancing the offset doesn't
                        # lose it, then fall through to commit past it.
                        try:
                            await publish_dead_letter(
                                worker=name,
                                original=rec.value,
                                error="handler raised",
                                topic=rec.topic,
                                partition=rec.partition,
                                offset=rec.offset,
                            )
                            handled = True
                            log.warning("[%s] dead-lettered offset=%s", name, rec.offset)
                        except Exception:  # noqa: BLE001 — DLQ itself unavailable
                            log.exception(
                                "[%s] dead-letter failed for offset=%s; NOT advancing (will redeliver)",
                                name,
                                rec.offset,
                            )
                # Manual commit-after-success: only advance once the record was
                # handled or safely parked. Commit per record so a crash never
                # strands an un-handled offset behind a committed one.
                if commit and handled:
                    try:
                        await consumer.commit()
                    except Exception:  # noqa: BLE001
                        log.exception("[%s] commit failed at offset=%s", name, rec.offset)

