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
import uuid

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.db import close_pool, execute, fetch_all, fetch_one, init_pool, system_scope
from app.services import bus, objective_controller

log = logging.getLogger("objective_worker")

EVENTS_TOPIC = "omni.events"
CONSUMER_GROUP = "v2-objective"
TRIGGER_EVENT = "campaign.run.completed"

# Watchdog — the loop is otherwise PURELY event-driven (it only wakes on
# campaign.run.completed). A re-seeded run that never completes — a hung source,
# a rate-limited connection, the send cap/window gate, a crashed muscle — would
# silently freeze its objective in 'pursuing' forever, with no re-evaluation and
# no exhaustion. The watchdog periodically re-pursues objectives that have been
# 'pursuing' with no progress update for longer than STALE_AFTER_S: it re-measures
# (progress may have moved), and if a widen is still warranted it re-seeds again —
# turning a silent freeze into a real decision. Idempotent: pursue() is a pure
# function of measured state, so a redundant sweep just re-measures and re-decides.
WATCHDOG_INTERVAL_S = 120  # how often the sweep runs
STALE_AFTER_S = 600        # a 'pursuing' objective idle this long is considered stalled


async def handle_event(env: dict) -> None:
    if (env.get("event_type") or "") != TRIGGER_EVENT:
        return
    workspace_id = env.get("workspace_id")
    payload = env.get("payload") or {}
    workflow_id = payload.get("workflow_id")
    if not workspace_id or not workflow_id:
        return
    correlation_id = str(env.get("correlation_id") or "")
    source_count = int(payload.get("run_source_count") or 1)
    if source_count > 1 and not await _multi_source_run_complete(
        str(workspace_id), str(workflow_id), correlation_id, source_count
    ):
        return
    try:
        await pursue(
            str(workspace_id),
            str(workflow_id),
            completion_correlation_id=correlation_id or None,
        )
    except Exception:
        if correlation_id:
            await _release_completion_claim(
                str(workspace_id), str(workflow_id), correlation_id
            )
        raise


async def _multi_source_run_complete(
    workspace_id: str,
    workflow_id: str,
    correlation_id: str,
    source_count: int,
) -> bool:
    """True once every source root in one logical run is terminal.

    Root leads carry the shared correlation id in custom_fields. This avoids
    treating each independently finishing source as a separate objective
    iteration.
    """
    if not correlation_id:
        return False
    async with system_scope():
        row = await fetch_one(
            """
            SELECT
                COUNT(*) AS roots,
                COUNT(*) FILTER (
                    WHERE status IN (
                        'completed','errored','cancelled','converted',
                        'ended','suppressed','invalid'
                    )
                ) AS terminal
            FROM omni_leads
            WHERE workspace_id=$1
              AND workflow_id=$2
              AND parent_lead_id IS NULL
              AND custom_fields->>'_run_correlation_id'=$3
            """,
            workspace_id,
            workflow_id,
            correlation_id,
        )
    roots = int((row or {}).get("roots") or 0)
    terminal = int((row or {}).get("terminal") or 0)
    return roots >= source_count and terminal >= source_count


async def _claim_completion(
    workspace_id: str,
    objective_id: str,
    completion_correlation_id: str,
) -> bool:
    """Acquire a recoverable lease for one completed logical run."""
    async with system_scope():
        row = await fetch_one(
            """
            UPDATE omni_campaign_objectives
            SET progress = COALESCE(progress, '{}'::jsonb)
                         || jsonb_build_object(
                              'processing_completion_correlation_id', $1::text,
                              'completion_claimed_at', NOW()::text
                            ),
                updated_at = NOW()
            WHERE id=$2 AND workspace_id=$3
              AND COALESCE(progress->>'last_completion_correlation_id', '') <> $1
              AND (
                    COALESCE(progress->>'processing_completion_correlation_id', '') = ''
                    OR NULLIF(progress->>'completion_claimed_at', '')::timestamptz
                        < NOW() - make_interval(secs => $4)
                  )
            RETURNING id
            """,
            completion_correlation_id,
            objective_id,
            workspace_id,
            STALE_AFTER_S,
        )
    return bool(row)


async def _release_completion_claim(
    workspace_id: str,
    workflow_id: str,
    completion_correlation_id: str,
) -> None:
    """Release a lease after a handled exception so event redelivery can retry."""
    async with system_scope():
        await execute(
            """
            UPDATE omni_campaign_objectives
            SET progress = COALESCE(progress, '{}'::jsonb)
                         - 'processing_completion_correlation_id'
                         - 'completion_claimed_at',
                updated_at = NOW()
            WHERE workflow_id=$1 AND workspace_id=$2
              AND progress->>'processing_completion_correlation_id'=$3
            """,
            workflow_id,
            workspace_id,
            completion_correlation_id,
        )


async def pursue(
    workspace_id: str,
    workflow_id: str,
    *,
    completion_correlation_id: str | None = None,
) -> None:
    """Measure this campaign's objective, decide, persist, and re-seed on widen.

    No-op when the workflow has no objective or it's terminal/paused."""
    async with system_scope():
        obj = await fetch_one(
            "SELECT * FROM omni_campaign_objectives WHERE workflow_id=$1 AND workspace_id=$2",
            workflow_id, workspace_id,
        )
    if not obj or obj["status"] in ("reached", "exhausted", "paused"):
        return
    if completion_correlation_id and not await _claim_completion(
        workspace_id, str(obj["id"]), completion_correlation_id
    ):
        log.info(
            "objective %s already evaluated completion %s",
            obj["id"],
            completion_correlation_id,
        )
        return

    progress = dict(obj.get("progress") or {})
    if completion_correlation_id:
        progress["last_completion_correlation_id"] = completion_correlation_id
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

    entries = await runner.entry_nodes(workflow_id, workspace_id)
    entry = entries[0] if entries else None
    entry_type = str(entry["node_type"]) if entry else ""
    overrides, summary = objective_controller.widen_audience(audience, iterations_used, entry_type)
    progress["iterations_used"] = iterations_used + 1
    progress["last_action"] = summary
    await _persist(workspace_id, str(obj["id"]), verdict.next_status, progress)

    correlation_id = str(uuid.uuid4())
    outcomes = []
    for index, source in enumerate(entries):
        source_type = str(source["node_type"])
        source_overrides, _source_summary = objective_controller.widen_audience(
            audience, iterations_used, source_type
        )
        outcomes.append(
            await runner.seed_and_run(
                workspace_id=workspace_id,
                workflow_id=workflow_id,
                start_node=source,
                config_overrides=source_overrides or overrides,
                correlation_id=correlation_id,
                run_source_count=len(entries),
                run_source_index=index,
            )
        )
    failures = [outcome for outcome in outcomes if outcome.error]
    if failures:
        log.warning(
            "objective re-seed had %d/%d source failures for %s: %s",
            len(failures), len(outcomes), workflow_id, [outcome.error for outcome in failures],
        )
    else:
        log.info(
            "objective re-seed: workflow %s re-ran %d sources (correlation=%s)",
            workflow_id, len(outcomes), correlation_id,
        )


async def _persist(workspace_id: str, objective_id: str, status: str, progress: dict) -> None:
    async with system_scope():
        await execute(
            "UPDATE omni_campaign_objectives SET status=$1, progress=$2::jsonb, updated_at=NOW() "
            "WHERE id=$3 AND workspace_id=$4",
            status, json.dumps(progress), objective_id, workspace_id,
        )


async def _watchdog_sweep() -> None:
    """Re-pursue objectives stuck in 'pursuing' with no update for STALE_AFTER_S.

    The event path only re-evaluates on run-completion, so a re-seed that never
    completes freezes its objective silently. This finds those (status='pursuing'
    AND updated_at older than the threshold) and re-pursues each — re-measuring
    and, if still short within bounds, re-seeding. updated_at is bumped on every
    _persist, so a healthy looping objective is never stale; only a genuinely
    stalled one trips this. Cross-tenant read (system-scoped, like the rest of the
    worker) — pursue() re-asserts workspace scope per objective."""
    async with system_scope():
        rows = await fetch_all(
            "SELECT workspace_id, workflow_id FROM omni_campaign_objectives "
            "WHERE status = 'pursuing' "
            "AND updated_at < NOW() - make_interval(secs => $1)",
            STALE_AFTER_S,
        )
    if not rows:
        return
    log.info("[objective] watchdog: %d stalled objective(s) — re-pursuing", len(rows))
    for r in rows:
        try:
            await pursue(str(r["workspace_id"]), str(r["workflow_id"]))
        except Exception:  # noqa: BLE001
            # One wedged objective must not kill the sweep for the others.
            log.exception("[objective] watchdog re-pursue failed for workflow %s", r["workflow_id"])


async def _watchdog_loop(stop: asyncio.Event) -> None:
    """Run the stall sweep every WATCHDOG_INTERVAL_S until stop is set."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=WATCHDOG_INTERVAL_S)
        except TimeoutError:
            pass  # interval elapsed — time to sweep
        if stop.is_set():
            return
        try:
            await _watchdog_sweep()
        except Exception:  # noqa: BLE001
            log.exception("[objective] watchdog sweep errored; continuing")


async def run() -> None:
    await init_pool(settings.database_url)
    await bus.init_producer()
    # Re-seed fires the entry node via run.seed_and_run, which needs the node
    # registry populated — discover the nodes at startup (same as the transition
    # worker). Without this the registry is empty and get('source.searxng')
    # raises KeyError, so a widen can measure+decide but never re-run.
    import app.nodes as noderegistry

    noderegistry.discover()
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

    # The watchdog runs concurrently with the event consumer: the consumer drives
    # the loop when runs complete; the watchdog catches objectives whose re-seed
    # stalled and never produced a completion event.
    watchdog = asyncio.create_task(_watchdog_loop(stop))
    log.info("[objective] watchdog sweeping every %ds (stale after %ds)", WATCHDOG_INTERVAL_S, STALE_AFTER_S)
    try:
        await bus.consume_forever(consumer, handle_event, name="objective", stop_event=stop, commit=True)
    finally:
        stop.set()
        watchdog.cancel()
        try:
            await watchdog
        except asyncio.CancelledError:
            pass
        await consumer.stop()
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
