"""SOTA result synchronizer.

Consumes ``outreach.results`` (the receipts the Rust muscle publishes after
executing an ActionCommand) and reflects them back into Postgres for UI
parity and analytics. The muscle is forbidden from touching the live schema
itself; this worker is the only writer.

ExecutionResult envelope (see backend-rust/src/models.rs):

    {
      "command_id":      "<uuid>",                 # mirror of task_id
      "task_id":         "<uuid>",
      "lead_id":         "<uuid>",
      "campaign_id":     "<uuid>",
      "channel":         "linkedin_invite",
      "status":          "sent" | "failed" | "rate_limited" | "skipped" | "simulated",
      "error":           "<text or null>",
      "is_retriable":    true|false,
      "telemetry":       {...},
      "event_type":      "invite_sent",            # optional — mirrored to events
      "lead_mutations":  {                         # optional — applied to leads row
          "set":          {"chat_id": "...", "invited_at_now": true},
          "extra_data_set": {"ai_draft": "..."},
          "tag_add":      ["hot"],
          "tag_remove":   ["cold"]
      },
      "metadata":        {"next_handle": "fired", "node_id": "<uuid>"}
    }

The worker keeps three responsibilities tight:
  1. flip the queue row + processed_commands ledger
  2. apply lead mutations (so Rust never holds a DB transaction)
  3. mirror the event into ``events`` so analytics still works
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from aiokafka import AIOKafkaConsumer

from app.config import settings
from app.db import close_pool, execute, fetch_one, init_pool

log = logging.getLogger(__name__)


# Whitelist of lead columns the muscle is allowed to set directly. Anything
# outside this set falls into extra_data (or is dropped) so a malicious or
# buggy Rust handler can't reshape the schema. Keep this list small.
_ALLOWED_LEAD_COLUMNS: frozenset[str] = frozenset(
    {
        "chat_id",
        "ig_chat_id",
        "tg_chat_id",
        "invited_at",
        "accepted_at",
        "replied_at",
        "profile_viewed_at",
        "inmail_sent_at",
        "email_sent_at",
        "linkedin_distance",
        "last_contacted_at",
        "first_name",
        "last_name",
        "email",
        "phone",
        "company",
        "headline",
    }
)

# Mutation keys ending in "_now" are translated into ``column = NOW()`` so the
# muscle can claim a timestamp without carrying server clock state.
_NOW_SUFFIX = "_now"


async def _apply_lead_mutations(lead_id: str, mutations: dict[str, Any]) -> None:
    if not lead_id or not mutations:
        return

    set_fields = mutations.get("set") or {}
    extra_data_set = mutations.get("extra_data_set") or {}
    tag_add = mutations.get("tag_add") or []
    tag_remove = mutations.get("tag_remove") or []

    # Column writes.
    set_clauses: list[str] = []
    values: list[Any] = []
    idx = 2  # $1 is lead_id
    for raw_key, raw_val in set_fields.items():
        if not isinstance(raw_key, str):
            continue
        key = raw_key[: -len(_NOW_SUFFIX)] if raw_key.endswith(_NOW_SUFFIX) else raw_key
        if key not in _ALLOWED_LEAD_COLUMNS:
            log.warning("[sync-worker] dropped disallowed lead column %s", raw_key)
            continue
        if raw_key.endswith(_NOW_SUFFIX):
            set_clauses.append(f"{key}=NOW()")
        else:
            set_clauses.append(f"{key}=${idx}")
            values.append(raw_val)
            idx += 1

    if set_clauses:
        await execute(
            f"UPDATE leads SET {', '.join(set_clauses)} WHERE id=$1",
            lead_id,
            *values,
        )

    # extra_data merge.
    if extra_data_set:
        existing = await fetch_one("SELECT extra_data FROM leads WHERE id=$1", lead_id)
        merged = dict(existing.get("extra_data") or {}) if existing else {}
        merged.update(extra_data_set)
        await execute(
            "UPDATE leads SET extra_data=$1 WHERE id=$2",
            json.dumps(merged),
            lead_id,
        )

    # Tag mutations.
    for tag in tag_add:
        if not isinstance(tag, str) or not tag:
            continue
        await execute(
            "UPDATE leads SET tags = array_append(tags, $1) "
            "WHERE id=$2 AND NOT ($1 = ANY(tags))",
            tag,
            lead_id,
        )
    for tag in tag_remove:
        if not isinstance(tag, str) or not tag:
            continue
        await execute(
            "UPDATE leads SET tags = array_remove(tags, $1) WHERE id=$2",
            tag,
            lead_id,
        )


async def _record_event(
    lead_id: str | None,
    campaign_id: str | None,
    event_type: str | None,
    channel: str | None,
    meta: dict[str, Any] | None,
) -> None:
    if not event_type or not lead_id or not campaign_id:
        return
    try:
        await execute(
            """
            INSERT INTO events (lead_id, campaign_id, event_type, channel, meta, occurred_at)
            VALUES ($1, $2, $3, $4, $5, NOW())
            """,
            lead_id,
            campaign_id,
            event_type,
            channel,
            json.dumps(meta or {}),
        )
    except Exception as e:  # noqa: BLE001 — analytics must never break sync
        log.warning("[sync-worker] event insert failed (non-fatal): %s", e)


async def _process_result(data: dict[str, Any]) -> None:
    task_id = data.get("task_id") or data.get("command_id")
    status = (data.get("status") or "").lower()
    error = data.get("error")
    channel = data.get("channel")
    lead_id = data.get("lead_id")
    campaign_id = data.get("campaign_id")
    metadata = data.get("metadata") or {}
    telemetry = data.get("telemetry") or {}

    if not task_id:
        return

    # 1) Apply lead mutations FIRST so a transition_worker reading the same
    #    result later sees the post-execution lead state.
    mutations = data.get("lead_mutations") or {}
    if mutations and lead_id:
        try:
            await _apply_lead_mutations(str(lead_id), mutations)
        except Exception as e:  # noqa: BLE001
            log.error("[sync-worker] mutation apply failed for %s: %s", task_id, e)

    # 2) Update the legacy queue row + processed_commands ledger.
    if status == "sent" or status == "simulated":
        await execute(
            "UPDATE queue SET status='sent', sent_at=NOW(), failure_reason=NULL WHERE id=$1",
            task_id,
        )
        await execute(
            "UPDATE processed_commands SET status='sent', processed_at=NOW() WHERE command_id=$1",
            task_id,
        )
        if lead_id:
            await execute(
                "UPDATE leads SET last_contacted_at=NOW() WHERE id=$1",
                lead_id,
            )
    elif status == "failed":
        await execute(
            "UPDATE queue SET status='failed', failure_reason=$1 WHERE id=$2",
            error,
            task_id,
        )
        await execute(
            "UPDATE processed_commands SET status='failed', processed_at=NOW() WHERE command_id=$1",
            task_id,
        )
        log.error("[sync-worker] task %s FAILED: %s", task_id, error)
    elif status == "rate_limited":
        await execute(
            "UPDATE queue SET status='queued', failure_reason=$1, "
            "scheduled_at=NOW() + INTERVAL '5 minutes' WHERE id=$2",
            error or "rate_limited",
            task_id,
        )
        log.warning("[sync-worker] task %s RATE_LIMITED, re-queued in 5m", task_id)
    elif status == "skipped":
        await execute(
            "UPDATE queue SET status='skipped', failure_reason=$1 WHERE id=$2",
            error or "skipped",
            task_id,
        )
        await execute(
            "UPDATE processed_commands SET status='skipped', processed_at=NOW() WHERE command_id=$1",
            task_id,
        )

    # 3) Mirror the event into the analytics table.
    event_type = data.get("event_type")
    if event_type:
        meta = {
            **telemetry,
            **{k: v for k, v in metadata.items() if k not in {"node_id"}},
        }
        await _record_event(lead_id, campaign_id, event_type, channel, meta)


async def run_sync_worker() -> None:
    """Consumes results from Redpanda and syncs them back to Postgres."""
    consumer = AIOKafkaConsumer(
        "outreach.results",
        bootstrap_servers=settings.kafka_brokers,
        group_id="omni-postgres-sync",
        auto_offset_reset="earliest",
    )

    await consumer.start()
    log.info("[sync-worker] Started result-to-postgres bridge")

    try:
        async for msg in consumer:
            try:
                data = json.loads(msg.value)
            except json.JSONDecodeError as e:
                log.error("[sync-worker] bad JSON on outreach.results: %s", e)
                continue
            try:
                await _process_result(data)
            except Exception as e:  # noqa: BLE001 — never crash the loop
                log.exception("[sync-worker] processing failed: %s", e)
    finally:
        await consumer.stop()


async def main() -> None:
    await init_pool(settings.get_asyncpg_dsn())
    try:
        await run_sync_worker()
    finally:
        await close_pool()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
