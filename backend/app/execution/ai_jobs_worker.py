"""AI jobs worker — executes ad-hoc AI Studio jobs off the event stream.

Consumes ``ai.<kind>.queued`` events that AI Studio's ``POST /ai/jobs`` publishes
(operator clicks "Run scoring"/"Compose"/"Classify"). For each, it runs the model
(``app.services.ai_jobs``) and publishes the matching ``ai.<kind>.completed`` /
``ai.<kind>.failed`` fact onto omni.events — which the projector materialises into
the AI Studio run log and, for scores, the per-lead ``omni_lead_scores`` table.

Why a dedicated worker (not the dispatcher → muscle path): an ad-hoc Studio job is
NOT a lead advancing through a campaign DAG. It has no workflow node, and a score
is a non-advancing per-lead fact. The dispatcher only routes intents that resolve
to a real ``omni_workflow_nodes`` row, so it correctly DROPS node-less ad-hoc
intents (which is why the page used to queue jobs into a void). Forcing them
through the muscle would need synthetic leads (the SPINE-2 black hole). This is
the same operator-triggered-AI boundary ``reply_drafter`` documents: it stays in
Python, off the muscle hot path.

Distinguishing ad-hoc from in-workflow events: in-workflow AI runs carry a
``node_id`` in the payload (the dispatcher set it). Ad-hoc Studio jobs do not.
This worker only handles the node-less ones, so it never double-runs a node's AI.

kind=score:
  * entity_id set  → score that one lead.
  * entity_id None → batch: score the most recently active leads (bounded).
kind=compose:  entity_id = the lead to draft for; config carries the instruction.
kind=classify: config carries `body` (the reply text) to classify.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
from typing import Any

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.db import assert_rls_enforcing_role, close_pool, fetch_all, fetch_one, init_pool, system_scope
from app.services import ai_jobs, bus

log = logging.getLogger("ai_jobs_worker")

EVENTS_TOPIC = "omni.events"
CONSUMER_GROUP = "v2-ai-jobs"

# Ad-hoc score batch cap — one operator click shouldn't fan out unbounded model
# calls. Operators re-run to cover more; objectives drive volume the muscle way.
_SCORE_BATCH_LIMIT = 100

# NB: omni_contacts has no `location` column — location lives in custom_fields
# (see projections.py / lead_columns). _lead_facts derives it from there.
_LEAD_SELECT = """
    SELECT l.id, l.contact_id, l.custom_fields,
           c.first_name, c.last_name, c.email, c.company, c.headline,
           c.linkedin_url, c.source
    FROM omni_leads l
    LEFT JOIN omni_contacts c ON c.id = l.contact_id AND c.workspace_id = l.workspace_id
"""


def _is_adhoc_job_event(event_type: str, payload: dict) -> bool:
    """An ad-hoc AI Studio job: ``ai.<kind>.queued`` with NO node_id.

    In-workflow AI runs carry node_id (set by the dispatcher) — those belong to
    the muscle, not here."""
    if not event_type.startswith("ai.") or not event_type.endswith(".queued"):
        return False
    kind = event_type.split(".")[1]
    if kind not in ("score", "compose", "classify"):
        return False
    return not payload.get("node_id")


def _lead_facts(row: dict[str, Any]) -> dict[str, Any]:
    """The fact bundle handed to the model — contact identity + lead custom_fields."""
    cf = row.get("custom_fields") or {}
    if isinstance(cf, str):
        try:
            cf = json.loads(cf)
        except json.JSONDecodeError:
            cf = {}
    return {
        "first_name": row.get("first_name"),
        "last_name": row.get("last_name"),
        "company": row.get("company"),
        "headline": row.get("headline"),
        # location is not a contacts column — it lives in custom_fields.
        "location": cf.get("location"),
        "source": row.get("source"),
        "linkedin_url": row.get("linkedin_url"),
        "extra": {k: v for k, v in cf.items() if isinstance(v, (str, int, float, bool))},
    }


async def handle_event(env: dict) -> None:
    event_type = env.get("event_type") or ""
    payload = env.get("payload") or {}
    if not _is_adhoc_job_event(event_type, payload):
        return
    workspace_id = env.get("workspace_id")
    if not workspace_id:
        return
    kind = event_type.split(".")[1]
    correlation_id = env.get("correlation_id") or payload.get("correlation_id")

    api_key = await ai_jobs.anthropic_key(str(workspace_id))
    if not api_key:
        await _fail(workspace_id, kind, env.get("entity_id"), correlation_id,
                    "No Anthropic connection — add one in Integrations to run AI jobs.")
        return

    try:
        if kind == "score":
            await _run_score(str(workspace_id), env, payload, api_key, correlation_id)
        elif kind == "compose":
            await _run_compose(str(workspace_id), env, payload, api_key, correlation_id)
        elif kind == "classify":
            await _run_classify(str(workspace_id), env, payload, api_key, correlation_id)
    except ai_jobs.AiJobError as e:
        await _fail(workspace_id, kind, env.get("entity_id"), correlation_id, str(e))
    except Exception as e:  # noqa: BLE001 — never let one job crash the loop
        log.exception("ai job %s failed unexpectedly", kind)
        await _fail(workspace_id, kind, env.get("entity_id"), correlation_id, f"internal error: {e}")


async def _run_score(workspace_id: str, env: dict, payload: dict, api_key: str, cid: str | None) -> None:
    icp = (payload.get("icp_description") or payload.get("icp") or "").strip()
    if not icp:
        raise ai_jobs.AiJobError("score job needs an ICP description")

    entity_id = env.get("entity_id")
    async with system_scope():
        if entity_id:
            rows = await fetch_all(_LEAD_SELECT + " WHERE l.id = $1", entity_id)
        else:
            rows = await fetch_all(
                _LEAD_SELECT
                + " WHERE l.status NOT IN ('suppressed','cancelled')"
                + " ORDER BY l.updated_at DESC LIMIT $1",
                _SCORE_BATCH_LIMIT,
            )
    if not rows:
        raise ai_jobs.AiJobError("no leads to score")

    scored = 0
    for row in rows:
        result = await ai_jobs.score_lead(api_key, icp, _lead_facts(dict(row)))
        await bus.publish_event(
            workspace_id=workspace_id,
            event_type="ai.score.completed",
            entity_type="lead",
            entity_id=str(row["id"]),
            payload={
                "score": result["score"],
                "reasons": result["reasons"],
                "model": result["model"],
                "contact_id": str(row["contact_id"]) if row.get("contact_id") else None,
                # carry the originating job's correlation so the run-log row closes
                "correlation_id": cid,
            },
            correlation_id=cid,
        )
        scored += 1
    log.info("scored %d lead(s) for workspace %s (job %s)", scored, workspace_id, cid)


async def _run_compose(workspace_id: str, env: dict, payload: dict, api_key: str, cid: str | None) -> None:
    entity_id = env.get("entity_id")
    instruction = (payload.get("instruction") or "").strip()
    if not entity_id:
        raise ai_jobs.AiJobError("compose job needs a target lead")
    if not instruction:
        raise ai_jobs.AiJobError("compose job needs an instruction")
    async with system_scope():
        row = await fetch_one(_LEAD_SELECT + " WHERE l.id = $1", entity_id)
    if not row:
        raise ai_jobs.AiJobError("target lead not found")
    result = await ai_jobs.compose_message(
        api_key, instruction, _lead_facts(dict(row)),
        channel=payload.get("channel") or "email",
        tone=payload.get("tone") or "professional",
        max_words=int(payload.get("max_words") or 120),
    )
    await bus.publish_event(
        workspace_id=workspace_id,
        event_type="ai.compose.completed",
        entity_type="lead",
        entity_id=str(entity_id),
        payload={"draft": result["draft"], "model": result["model"], "correlation_id": cid},
        correlation_id=cid,
    )


async def _run_classify(workspace_id: str, env: dict, payload: dict, api_key: str, cid: str | None) -> None:
    body = (payload.get("body") or payload.get("text") or "").strip()
    if not body:
        raise ai_jobs.AiJobError("classify job needs a reply body")
    result = await ai_jobs.classify_reply(api_key, body)
    await bus.publish_event(
        workspace_id=workspace_id,
        event_type="ai.classify.completed",
        entity_type=env.get("entity_type") or "reply",
        entity_id=str(env["entity_id"]) if env.get("entity_id") else None,
        payload={**result, "correlation_id": cid},
        correlation_id=cid,
    )


async def _fail(workspace_id: str, kind: str, entity_id: Any, cid: str | None, reason: str) -> None:
    """Publish ai.<kind>.failed so the run-log row moves off 'queued' with a reason."""
    log.warning("ai job %s failed: %s", kind, reason)
    await bus.publish_event(
        workspace_id=str(workspace_id),
        event_type=f"ai.{kind}.failed",
        entity_type="lead" if kind in ("score", "compose") else "reply",
        entity_id=str(entity_id) if entity_id else None,
        payload={"error": reason, "correlation_id": cid},
        correlation_id=cid,
    )


async def run() -> None:
    await init_pool(settings.database_url)
    await assert_rls_enforcing_role()
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
    log.info("[ai_jobs] consuming %s for ad-hoc ai.<kind>.queued", EVENTS_TOPIC)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await bus.consume_forever(consumer, handle_event, name="ai_jobs", stop_event=stop, commit=True)
    finally:
        await consumer.stop()
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
