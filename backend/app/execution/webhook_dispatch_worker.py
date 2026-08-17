"""Outbound webhook fan-out worker (N8N-001 Part 2b, service: webhooks-out-v2).

Consumes the durable fact stream (``omni.events``), filters to the FIXED
allow-list of customer-facing events (app.services.webhook_events.ALLOWED_EVENTS
— internal spine facts are never leaked), maps the raw fact name to its
customer-facing event name, and delivers a normalized, HMAC-signed JSON envelope
to every active ``omni_webhook_subscriptions`` row for that workspace whose
``event_types`` include it (empty = all).

Mirrors the shape of ai_jobs_worker / objective_worker (a compose service in the
backend image). Delivery is SSRF-guarded and retried with backoff; a failure
records ``last_status`` + a delivery row and NEVER crashes the worker or blocks
other deliveries.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import signal

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.db import (
    assert_rls_enforcing_role,
    close_pool,
    execute,
    fetch_all,
    init_pool,
    system_scope,
)
from app.services import bus, webhook_events

log = logging.getLogger("webhook_dispatch_worker")

EVENTS_TOPIC = "omni.events"
CONSUMER_GROUP = "v2-webhooks-out"

# Retry schedule (seconds) for a delivery that gets a retryable failure
# (network error or 5xx). 4xx is not retried — the receiver rejected it.
_RETRY_BACKOFF = (1.0, 5.0, 15.0)


def _is_retryable(status_code: int | None) -> bool:
    """Network failure (None) or 5xx is worth retrying; 4xx is a client reject."""
    return status_code is None or status_code >= 500


async def _load_subscriptions(workspace_id: str, event: str) -> list[dict]:
    """Active subscriptions for this workspace that want ``event`` (empty = all).

    Runs under system_scope() — the worker spans tenants; it filters by the
    fact's workspace_id explicitly."""
    async with system_scope():
        rows = await fetch_all(
            "SELECT id, url, event_types, secret FROM omni_webhook_subscriptions "
            "WHERE workspace_id = $1 AND active = TRUE",
            workspace_id,
        )
    out = []
    for r in rows:
        event_types = r.get("event_types")
        if isinstance(event_types, str):
            try:
                event_types = json.loads(event_types)
            except json.JSONDecodeError:
                event_types = []
        if not event_types or event in event_types:
            out.append({**r, "event_types": event_types})
    return out


async def _record_delivery(
    workspace_id: str, subscription_id: str, event: str, status_code: int | None,
    attempts: int, body_digest: str, error: str | None,
) -> None:
    """Persist a delivery row + update the subscription's last_status. Best-effort."""
    try:
        async with system_scope():
            await execute(
                "INSERT INTO omni_webhook_deliveries "
                "(workspace_id, subscription_id, event_type, status_code, attempts, payload_digest, error) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7)",
                workspace_id, subscription_id, event, status_code, attempts, body_digest, error,
            )
            await execute(
                "UPDATE omni_webhook_subscriptions SET last_delivery_at = NOW(), last_status = $1 "
                "WHERE id = $2",
                status_code, subscription_id,
            )
    except Exception:  # noqa: BLE001 — logging a delivery must never break the loop
        log.exception("failed recording delivery for subscription %s", subscription_id)


async def _deliver_with_retry(
    workspace_id: str, sub: dict, event: str, data: dict
) -> None:
    """Deliver one envelope to one subscription, retrying retryable failures."""
    body_digest = hashlib.sha256(
        json.dumps(data, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()
    status_code: int | None = None
    error: str | None = None
    attempts = 0
    for attempt in range(len(_RETRY_BACKOFF) + 1):
        attempts = attempt + 1
        status_code, error = await webhook_events.deliver_one(
            url=sub["url"], secret=sub["secret"], event=event,
            workspace_id=workspace_id, data=data,
        )
        if error is None:
            break
        if not _is_retryable(status_code):
            break  # client reject (4xx / blocked URL) — no retry
        if attempt < len(_RETRY_BACKOFF):
            await asyncio.sleep(_RETRY_BACKOFF[attempt])
    if error:
        log.warning("delivery to %s failed after %d attempt(s): %s", sub["url"], attempts, error)
    await _record_delivery(
        workspace_id, str(sub["id"]), event, status_code, attempts, body_digest, error
    )


async def handle_event(env: dict) -> None:
    event_type = env.get("event_type") or ""
    event = webhook_events.map_fact(event_type)
    if not event or event not in webhook_events.ALLOWED_EVENTS:
        return  # internal spine fact — never delivered
    workspace_id = env.get("workspace_id")
    if not workspace_id:
        return
    subs = await _load_subscriptions(str(workspace_id), event)
    if not subs:
        return
    data = {
        "entity_type": env.get("entity_type"),
        "entity_id": env.get("entity_id"),
        "occurred_at": env.get("occurred_at"),
        "payload": env.get("payload") or {},
        "correlation_id": env.get("correlation_id"),
    }
    # Deliver to each subscription independently — one failure can't block others.
    await asyncio.gather(
        *(_deliver_with_retry(str(workspace_id), sub, event, data) for sub in subs),
        return_exceptions=True,
    )


async def run() -> None:
    await init_pool(settings.get_asyncpg_dsn())
    await assert_rls_enforcing_role()
    await bus.init_producer()
    consumer = AIOKafkaConsumer(
        EVENTS_TOPIC,
        bootstrap_servers=settings.kafka_brokers,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        enable_auto_commit=False,
        auto_offset_reset="latest",
    )
    await consumer.start()
    log.info("[webhooks-out] consuming %s for customer-facing events", EVENTS_TOPIC)

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, stop.set)
        except NotImplementedError:
            pass

    try:
        await bus.consume_forever(consumer, handle_event, name="webhooks_out", stop_event=stop, commit=True)
    finally:
        await consumer.stop()
        await bus.close_producer()
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(run())
