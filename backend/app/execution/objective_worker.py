"""Objective worker — the goal-pursuit control loop, on the event stream.

Consumes ``campaign.run.completed`` (emitted by the transition worker when a
campaign's root run-lead terminalizes) and pursues each workflow's objective:

  measure (lineage-scoped) -> decide (pure) -> persist -> if 'widen', re-seed
  the workflow via the SHARED run path with a widened sourcing config.

Why a dedicated worker instead of inline in the transition worker:
  * the goal loop is feedback CONTROL over run outcomes — a different genus than
    advancing one lead through the DAG. It belongs off the safety-critical
    terminalize claim, not inside it.
  * event-sourced: the trigger is a durable Kafka fact, so the loop survives a
    crash (redelivery re-evaluates) and is traceable by correlation_id, instead
    of a synchronous side-effect a crash could silently lose.
  * it can re-seed through the same app.execution.run.seed_and_run the /run
    endpoint uses — one seed path, no drift.

Idempotency: the controller increments iterations_used ONLY on a widen, and the
decision is a pure function of measured state, so a redelivered completion event
just re-measures and re-decides (it won't double-count the bounds). A re-seed
that fires twice would create two root leads — bounded by max_iterations, and
the next completion measures the (now higher) progress, so it self-corrects.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.db import close_pool, execute, fetch_one, init_pool, system_scope
from app.services import bus, objective_controller

log = logging.getLogger("objective_worker")

EVENTS_TOPIC = "omni.events"
CONSUMER_GROUP = "v2-objective"
TRIGGER_EVENT = "campaign.run.completed"


async def handle_event(env: dict) -> None:
    if (env.get("event_type") or "") != TRIGGER_EVENT:
        return
    workspace_id = env.get("workspace_id")
    payload = env.get("payload") or {}
    workflow_id = payload.get("workflow_id")
    if not workspace_id or not workflow_id:
        return
    await pursue(str(workspace_id), str(workflow_id))


async def pursue(workspace_id: str, workflow_id: str) -> None:
    """Measure this campaign's objective, decide, persist, and re-seed on widen.

    No-op when the workflow has no objective or it's terminal/paused."""
    async with system_scope():
        obj = await fetch_one(
            "SELECT * FROM omni_campaign_objectives WHERE workflow_id=$1 AND workspace_id=$2",
            workflow_id, workspace_id,
        )
    if not obj or obj["status"] in ("reached", "exhausted", "paused"):
        return

    progress = dict(obj.get("progress") or {})
    bounds = dict(obj.get("bounds") or {})
    audience = dict(obj.get("audience") or {})
    iterations_used = int(progress.get("iterations_used") or 0)

    current = await objective_controller.measure(workspace_id, obj["metric"], workflow_id)
    spend = await objective_controller.spend(workspace_id, workflow_id)
    verdict = objective_controller.decide(
        current=current,
        target=int(obj["target"]),
        iterations_used=iterations_used,
        spend_usd=spend,
        bounds=bounds,
    )
    log.info(
        "objective %s (%s %d/%d): %s — %s",
        obj["id"], obj["metric"], current, obj["target"], verdict.decision, verdict.reason,
    )

    progress.update({"current": current, "spend_usd": spend, "last_action": verdict.reason})

    if verdict.decision != "widen":
        await _persist(workspace_id, str(obj["id"]), verdict.next_status, progress)
        return

    # Widen: advance the sourcing ladder and re-seed via the shared run path.
    from app.execution import run as runner

    entry = await runner.entry_node(workflow_id, workspace_id)
    entry_type = str(entry["node_type"]) if entry else ""
    overrides, summary = objective_controller.widen_audience(audience, iterations_used, entry_type)
    progress["iterations_used"] = iterations_used + 1
    progress["last_action"] = summary
    await _persist(workspace_id, str(obj["id"]), verdict.next_status, progress)

    outcome = await runner.seed_and_run(
        workspace_id=workspace_id,
        workflow_id=workflow_id,
        start_node=entry,
        config_overrides=overrides,
    )
    if outcome.error:
        log.warning("objective re-seed failed for %s: %s", workflow_id, outcome.error)
    else:
        log.info("objective re-seed: workflow %s re-ran (lead %s, overrides=%s)", workflow_id, outcome.lead_id, overrides)


async def _persist(workspace_id: str, objective_id: str, status: str, progress: dict) -> None:
    async with system_scope():
        await execute(
            "UPDATE omni_campaign_objectives SET status=$1, progress=$2::jsonb, updated_at=NOW() "
            "WHERE id=$3 AND workspace_id=$4",
            status, json.dumps(progress), objective_id, workspace_id,
        )


async def run() -> None:
    await init_pool(settings.database_url)
    await bus.init_producer()
    consumer = AIOKafkaConsumer(
        EVENTS_TOPIC,
        bootstrap_servers=settings.kafka_brokers,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    log.info("[objective] consuming %s for %s", EVENTS_TOPIC, TRIGGER_EVENT)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await bus.consume_forever(consumer, handle_event, name="objective", stop_event=stop, commit=True)
    finally:
        await consumer.stop()
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
