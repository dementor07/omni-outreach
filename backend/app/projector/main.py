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
          email         = COALESCE(EXCLUDED.email,         contacts.email),
          first_name    = COALESCE(EXCLUDED.first_name,    contacts.first_name),
          last_name     = COALESCE(EXCLUDED.last_name,     contacts.last_name),
          company       = COALESCE(EXCLUDED.company,       contacts.company),
          headline      = COALESCE(EXCLUDED.headline,      contacts.headline),
          linkedin_url  = COALESCE(EXCLUDED.linkedin_url,  contacts.linkedin_url),
          phone         = COALESCE(EXCLUDED.phone,         contacts.phone),
          source        = COALESCE(EXCLUDED.source,        contacts.source),
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
          name          = COALESCE(EXCLUDED.name,     companies.name),
          domain        = COALESCE(EXCLUDED.domain,   companies.domain),
          industry      = COALESCE(EXCLUDED.industry, companies.industry),
          size          = COALESCE(EXCLUDED.size,     companies.size),
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
          name          = COALESCE(EXCLUDED.name,          deals.name),
          stage         = COALESCE(EXCLUDED.stage,         deals.stage),
          value         = COALESCE(EXCLUDED.value,         deals.value),
          currency      = COALESCE(EXCLUDED.currency,      deals.currency),
          contact_id    = COALESCE(EXCLUDED.contact_id,    deals.contact_id),
          company_id    = COALESCE(EXCLUDED.company_id,    deals.company_id),
          owner_user_id = COALESCE(EXCLUDED.owner_user_id, deals.owner_user_id),
          close_date    = COALESCE(EXCLUDED.close_date,    deals.close_date),
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
          contact_id      = COALESCE(EXCLUDED.contact_id,      leads.contact_id),
          workflow_id     = COALESCE(EXCLUDED.workflow_id,     leads.workflow_id),
          current_node_id = COALESCE(EXCLUDED.current_node_id, leads.current_node_id),
          status          = COALESCE(EXCLUDED.status,          leads.status),
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
    try:
        async for rec in consumer:
            env = rec.value
            try:
                async with system_scope():
                    inserted = await _archive_event(env, rec)
                    if inserted:
                        await _apply_projection(env)
                    await _record_offset(rec)
                await consumer.commit()
            except Exception as e:  # noqa: BLE001 — never kill the loop
                log.exception("[projector] failed to process offset=%s: %s", rec.offset, e)
    finally:
        await consumer.stop()


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    await init_pool(settings.get_asyncpg_dsn())
    try:
        await run()
    finally:
        await close_pool()


if __name__ == "__main__":
    asyncio.run(main())
