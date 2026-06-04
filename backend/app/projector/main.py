"""Projector worker.

Consumes ``omni.events`` from Redpanda. For every event:

  1. Inserts a row into ``events_archive`` (idempotent via UNIQUE
     (topic, partition, offset)).
  2. Updates the appropriate projection table (``contacts``, ``companies``,
     ``deals``, ``leads``, ``messages``) based on ``event_type``.
  3. Records the offset in ``projector_offsets`` so a restart resumes
     from the right place.

Runs system-scoped (cross-tenant by design; the workspace_id on every
event drives which tenant slice gets written).
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import ConsumerRecord

from app.config import settings
from app.db import close_pool, execute, fetch_one, init_pool, system_scope
from app.services import bus
from app.services.bus import EVENTS_TOPIC

log = logging.getLogger(__name__)

CONSUMER_GROUP = "omni-projector-v1"


async def _archive_event(env: dict[str, Any], rec: ConsumerRecord) -> bool:
    """Insert into events_archive. Returns False if duplicate (offset already seen)."""
    row = await fetch_one(
        """
        INSERT INTO omni_events_archive
          (id, workspace_id, event_type, entity_type, entity_id, payload,
           actor_user_id, correlation_id, kafka_topic, kafka_partition,
           kafka_offset, occurred_at)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9, $10, $11, $12)
        ON CONFLICT (kafka_topic, kafka_partition, kafka_offset) DO NOTHING
        RETURNING id
        """,
        env["id"],
        env["workspace_id"],
        env["event_type"],
        env["entity_type"],
        env.get("entity_id"),
        env.get("payload") or {},
        env.get("actor_user_id"),
        env.get("correlation_id"),
        rec.topic,
        rec.partition,
        rec.offset,
        datetime.fromisoformat(env["occurred_at"]),
    )
    return row is not None


# ── Projection upserts ────────────────────────────────────────────────────────


async def _project_contact(env: dict[str, Any]) -> None:
    p = env.get("payload") or {}
    await execute(
        """
        INSERT INTO omni_contacts (id, workspace_id, email, first_name, last_name,
                              company, headline, linkedin_url, phone, source, custom_fields)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
        ON CONFLICT (id) DO UPDATE SET
          email         = COALESCE(EXCLUDED.email,         omni_contacts.email),
          first_name    = COALESCE(EXCLUDED.first_name,    omni_contacts.first_name),
          last_name     = COALESCE(EXCLUDED.last_name,     omni_contacts.last_name),
          company       = COALESCE(EXCLUDED.company,       omni_contacts.company),
          headline      = COALESCE(EXCLUDED.headline,      omni_contacts.headline),
          linkedin_url  = COALESCE(EXCLUDED.linkedin_url,  omni_contacts.linkedin_url),
          phone         = COALESCE(EXCLUDED.phone,         omni_contacts.phone),
          source        = COALESCE(EXCLUDED.source,        omni_contacts.source),
          custom_fields = omni_contacts.custom_fields || EXCLUDED.custom_fields,
          updated_at    = NOW()
        """,
        env["entity_id"],
        env["workspace_id"],
        p.get("email"),
        p.get("first_name"),
        p.get("last_name"),
        p.get("company"),
        p.get("headline"),
        p.get("linkedin_url"),
        p.get("phone"),
        p.get("source"),
        p.get("custom_fields") or {},
    )


async def _project_company(env: dict[str, Any]) -> None:
    p = env.get("payload") or {}
    await execute(
        """
        INSERT INTO omni_companies (id, workspace_id, name, domain, industry, size, custom_fields)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        ON CONFLICT (id) DO UPDATE SET
          name          = COALESCE(EXCLUDED.name,     omni_companies.name),
          domain        = COALESCE(EXCLUDED.domain,   omni_companies.domain),
          industry      = COALESCE(EXCLUDED.industry, omni_companies.industry),
          size          = COALESCE(EXCLUDED.size,     omni_companies.size),
          custom_fields = omni_companies.custom_fields || EXCLUDED.custom_fields,
          updated_at    = NOW()
        """,
        env["entity_id"],
        env["workspace_id"],
        p.get("name") or "Unnamed",
        p.get("domain"),
        p.get("industry"),
        p.get("size"),
        p.get("custom_fields") or {},
    )


async def _project_deal(env: dict[str, Any]) -> None:
    p = env.get("payload") or {}
    await execute(
        """
        INSERT INTO omni_deals (id, workspace_id, name, stage, value, currency,
                           contact_id, company_id, owner_user_id, close_date, custom_fields)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb)
        ON CONFLICT (id) DO UPDATE SET
          name          = COALESCE(EXCLUDED.name,          omni_deals.name),
          stage         = COALESCE(EXCLUDED.stage,         omni_deals.stage),
          value         = COALESCE(EXCLUDED.value,         omni_deals.value),
          currency      = COALESCE(EXCLUDED.currency,      omni_deals.currency),
          contact_id    = COALESCE(EXCLUDED.contact_id,    omni_deals.contact_id),
          company_id    = COALESCE(EXCLUDED.company_id,    omni_deals.company_id),
          owner_user_id = COALESCE(EXCLUDED.owner_user_id, omni_deals.owner_user_id),
          close_date    = COALESCE(EXCLUDED.close_date,    omni_deals.close_date),
          custom_fields = omni_deals.custom_fields || EXCLUDED.custom_fields,
          updated_at    = NOW()
        """,
        env["entity_id"],
        env["workspace_id"],
        p.get("name") or "Unnamed",
        p.get("stage") or "new",
        p.get("value"),
        p.get("currency") or "USD",
        p.get("contact_id"),
        p.get("company_id"),
        p.get("owner_user_id"),
        p.get("close_date"),
        p.get("custom_fields") or {},
    )


async def _project_lead(env: dict[str, Any]) -> None:
    p = env.get("payload") or {}
    await execute(
        """
        INSERT INTO omni_leads (id, workspace_id, contact_id, workflow_id,
                           current_node_id, status, custom_fields)
        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
        ON CONFLICT (id) DO UPDATE SET
          contact_id      = COALESCE(EXCLUDED.contact_id,      omni_leads.contact_id),
          workflow_id     = COALESCE(EXCLUDED.workflow_id,     omni_leads.workflow_id),
          current_node_id = COALESCE(EXCLUDED.current_node_id, omni_leads.current_node_id),
          status          = COALESCE(EXCLUDED.status,          omni_leads.status),
          custom_fields   = omni_leads.custom_fields || EXCLUDED.custom_fields,
          updated_at      = NOW()
        """,
        env["entity_id"],
        env["workspace_id"],
        p.get("contact_id"),
        p.get("workflow_id"),
        p.get("current_node_id"),
        p.get("status") or "active",
        p.get("custom_fields") or {},
    )


async def _project_message(env: dict[str, Any]) -> None:
    p = env.get("payload") or {}
    direction = "inbound" if env["event_type"] == "message.received" else "outbound"
    await execute(
        """
        INSERT INTO omni_messages (id, workspace_id, contact_id, channel, direction,
                              subject, body, classification, confidence, metadata, occurred_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10::jsonb, $11)
        ON CONFLICT (id) DO NOTHING
        """,
        env["id"],
        env["workspace_id"],
        p.get("contact_id"),
        p.get("channel") or "unknown",
        direction,
        p.get("subject"),
        p.get("body"),
        p.get("classification"),
        p.get("confidence"),
        p.get("metadata") or {},
        datetime.fromisoformat(env["occurred_at"]),
    )


def _score_to_tier(score: int) -> str:
    """Map a 0-100 ICP score to a hot/warm/cold tier (HubSpot-style)."""
    if score >= 70:
        return "hot"
    if score >= 40:
        return "warm"
    return "cold"


async def _project_lead_score(env: dict[str, Any]) -> None:
    """Latest ICP score per lead. Fed by ai.score.completed."""
    p = env.get("payload") or {}
    score = int(p.get("score") or 0)
    score = max(0, min(100, score))
    await execute(
        """
        INSERT INTO omni_lead_scores (lead_id, workspace_id, contact_id, score,
                                      tier, reasons, model, correlation_id, scored_at)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, NOW())
        ON CONFLICT (lead_id) DO UPDATE SET
          contact_id     = COALESCE(EXCLUDED.contact_id, omni_lead_scores.contact_id),
          score          = EXCLUDED.score,
          tier           = EXCLUDED.tier,
          reasons        = EXCLUDED.reasons,
          model          = EXCLUDED.model,
          correlation_id = EXCLUDED.correlation_id,
          scored_at      = NOW()
        """,
        env["entity_id"],
        env["workspace_id"],
        p.get("contact_id"),
        score,
        _score_to_tier(score),
        p.get("reasons") or [],
        p.get("model"),
        env.get("correlation_id"),
    )


# Map an ai.<kind>.<phase> event_type to (kind, status).
_AI_JOB_LIFECYCLE = {
    "queued": "queued",
    "running": "running",
    "completed": "done",
    "failed": "failed",
}


async def _project_ai_job(env: dict[str, Any]) -> None:
    """AI Studio run log. ai.<kind>.queued inserts; .completed/.failed update.

    event_type is dotted: ``ai.score.queued``, ``ai.compose.completed`` …
    """
    parts = env["event_type"].split(".")
    if len(parts) != 3 or parts[0] != "ai":
        return
    _, kind, phase = parts
    # Screen nodes emit ai.screen_company.* / ai.screen_person.*; the muscle
    # result envelope uses ai.screen.completed. Collapse all screen variants to
    # the single audit kind 'screen' so the run log records them regardless of
    # which naming scheme produced the event. (omni_ai_jobs.kind allows 'screen'
    # as of migration 024.)
    if kind.startswith("screen"):
        kind = "screen"
    if kind not in ("score", "compose", "enrich", "classify", "screen"):
        return
    status = _AI_JOB_LIFECYCLE.get(phase)
    if status is None:
        return

    p = env.get("payload") or {}
    correlation_id = env.get("correlation_id")

    if status == "queued":
        # Insert a new job row keyed by correlation_id (or event id fallback).
        await execute(
            """
            INSERT INTO omni_ai_jobs (id, workspace_id, kind, status, entity_type,
                                      entity_id, input, model, correlation_id, created_at)
            VALUES ($1, $2, $3, 'queued', $4, $5, $6::jsonb, $7, $8, NOW())
            ON CONFLICT (id) DO NOTHING
            """,
            correlation_id or env["id"],
            env["workspace_id"],
            kind,
            env.get("entity_type"),
            env.get("entity_id"),
            p,
            p.get("provider") or p.get("model"),
            correlation_id,
        )
        return

    # Terminal/running phase — update the matching job row by correlation_id.
    await execute(
        """
        UPDATE omni_ai_jobs SET
          status       = $2,
          output       = CASE WHEN $3::jsonb = '{}'::jsonb THEN output ELSE $3::jsonb END,
          model        = COALESCE($4, model),
          cost_usd     = COALESCE($5, cost_usd),
          error        = COALESCE($6, error),
          completed_at = CASE WHEN $2 IN ('done','failed') THEN NOW() ELSE completed_at END
        WHERE id = $1
        """,
        correlation_id or env["id"],
        status,
        p.get("output") or {},
        p.get("model"),
        p.get("cost_usd"),
        p.get("error"),
    )


# Dispatch by entity_type — adding a new entity = one entry here.
_PROJECTORS = {
    "contact": _project_contact,
    "company": _project_company,
    "deal": _project_deal,
    "lead": _project_lead,
}


async def _apply_projection(env: dict[str, Any]) -> None:
    et = env["event_type"]
    entity = env["entity_type"]
    if et in ("message.received", "message.sent"):
        await _project_message(env)
        return
    # AI lifecycle events feed two projections: the job log (always) and,
    # for completed scores, the per-lead score table.
    if et.startswith("ai."):
        await _project_ai_job(env)
        if et == "ai.score.completed" and env.get("entity_id"):
            await _project_lead_score(env)
        return
    if entity in _PROJECTORS and env.get("entity_id"):
        await _PROJECTORS[entity](env)


async def _record_offset(rec: ConsumerRecord) -> None:
    await execute(
        """
        INSERT INTO omni_projector_offsets (kafka_topic, kafka_partition, kafka_offset, updated_at)
        VALUES ($1, $2, $3, NOW())
        ON CONFLICT (kafka_topic, kafka_partition) DO UPDATE
          SET kafka_offset = EXCLUDED.kafka_offset, updated_at = NOW()
        """,
        rec.topic,
        rec.partition,
        rec.offset,
    )


async def run() -> None:
    consumer = AIOKafkaConsumer(
        EVENTS_TOPIC,
        bootstrap_servers=settings.kafka_brokers,
        group_id=CONSUMER_GROUP,
        value_deserializer=lambda b: json.loads(b.decode("utf-8")),
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    log.info("[projector] consuming %s", EVENTS_TOPIC)

    async def _handle(rec) -> None:
        # The projector needs the record itself (offset bookkeeping), so it
        # takes the raw record rather than just the value. consume_forever
        # passes rec.value to handler; we pass a thin wrapper via on_record
        # instead so we keep offset access.
        env = rec.value
        async with system_scope():
            inserted = await _archive_event(env, rec)
            if inserted:
                await _apply_projection(env)
            await _record_offset(rec)
        await consumer.commit()

    try:
        # handler is a no-op; all work (incl. manual commit) happens in
        # on_record where we still have the record + offset. This keeps the
        # codec-skip / crash-tolerance guarantees of consume_forever.
        await bus.consume_forever(
            consumer,
            lambda _value: _noop(),
            name="projector",
            on_record=_handle,
        )
    finally:
        await consumer.stop()


async def _noop() -> None:
    return None


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await init_pool(settings.get_asyncpg_dsn())
    try:
        await run()
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
