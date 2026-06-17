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


async def _project_task(env: dict[str, Any]) -> None:
    """CONTRACT-004: persist crm.create_task's ``task.created`` into omni_tasks.

    The node carries a title *template*; we store the rendered title when the
    payload already has a concrete ``title``, else fall back to the template
    string verbatim (rendering happens upstream in the node context). due_date is
    an ISO date string."""
    p = env.get("payload") or {}
    due_date = p.get("due_date")
    await execute(
        """
        INSERT INTO omni_tasks (id, workspace_id, contact_id, title, due_date,
                           assign_to_user_id, priority, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'open')
        ON CONFLICT (id) DO NOTHING
        """,
        env["entity_id"],
        env["workspace_id"],
        p.get("contact_id"),
        p.get("title") or p.get("title_template") or "Task",
        datetime.fromisoformat(due_date).date() if due_date else None,
        p.get("assign_to_user_id"),
        p.get("priority") or "normal",
    )


async def _project_approval(env: dict[str, Any]) -> None:
    """CONTRACT-005: track the approvals queue.

    ``approval.requested`` inserts a pending row (keyed by lead_id so a node only
    has one open approval per lead). ``approval.resolved`` flips it to the
    operator's outcome. Both keyed on lead_id via the unique-ish (id) PK derived
    from entity_id (the lead id), so resolution updates the same row."""
    p = env.get("payload") or {}
    et = env["event_type"]
    if et == "approval.requested":
        await execute(
            """
            INSERT INTO omni_approvals (id, workspace_id, lead_id, node_id, prompt,
                               draft, status, correlation_id)
            VALUES ($1, $2, $3, $4, $5, $6, 'pending', $7)
            ON CONFLICT (id) DO NOTHING
            """,
            env["entity_id"],
            env["workspace_id"],
            p.get("lead_id") or env["entity_id"],
            p.get("node_id"),
            p.get("prompt") or "",
            p.get("draft"),
            env.get("correlation_id"),
        )
    elif et == "approval.draft_updated":
        # B1: operator edited the AI draft before approving. Only a still-pending
        # approval's draft is mutable; a resolved one is frozen.
        await execute(
            """
            UPDATE omni_approvals
               SET draft = $1
             WHERE id = $2 AND workspace_id = $3 AND status = 'pending'
            """,
            p.get("draft") or "",
            env["entity_id"],
            env["workspace_id"],
        )
    elif et == "approval.resolved":
        await execute(
            """
            UPDATE omni_approvals
               SET status = $1, resolved_handle = $1, resolved_by = $2,
                   resolved_at = NOW()
             WHERE id = $3 AND workspace_id = $4 AND status = 'pending'
            """,
            p.get("handle") or "approved",
            p.get("resolved_by"),
            env["entity_id"],
            env["workspace_id"],
        )


async def _project_pipeline_metric(env: dict[str, Any]) -> None:
    """Per-run pipeline cost/usage metrics. Each ``pipeline.metric`` event carries
    deltas that ACCUMULATE into the run row (the event-sourced fan-out emits one
    per company/person/lead). entity_id = run_id; payload.kind 'start'|'delta'|'end'."""
    p = env.get("payload") or {}
    kind = p.get("kind", "delta")
    if kind == "start":
        await execute(
            """
            INSERT INTO omni_pipeline_metrics (run_id, workspace_id, collector_source, correlation_id, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            ON CONFLICT (run_id) DO NOTHING
            """,
            env["entity_id"],
            env["workspace_id"],
            p.get("collector_source"),
            env.get("correlation_id"),
            p.get("metadata") or {},
        )
        return
    # delta / end: accumulate counters; 'end' also stamps completed_at.
    await execute(
        """
        INSERT INTO omni_pipeline_metrics (
            run_id, workspace_id, collector_source,
            companies_collected, companies_qualified, companies_rejected,
            people_found, people_verified, leads_created,
            serper_calls, claude_calls, claude_input_tokens, claude_output_tokens, total_cost,
            completed_at
        ) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
        ON CONFLICT (run_id) DO UPDATE SET
            companies_collected  = omni_pipeline_metrics.companies_collected  + EXCLUDED.companies_collected,
            companies_qualified  = omni_pipeline_metrics.companies_qualified  + EXCLUDED.companies_qualified,
            companies_rejected   = omni_pipeline_metrics.companies_rejected   + EXCLUDED.companies_rejected,
            people_found         = omni_pipeline_metrics.people_found         + EXCLUDED.people_found,
            people_verified      = omni_pipeline_metrics.people_verified      + EXCLUDED.people_verified,
            leads_created        = omni_pipeline_metrics.leads_created        + EXCLUDED.leads_created,
            serper_calls         = omni_pipeline_metrics.serper_calls         + EXCLUDED.serper_calls,
            claude_calls         = omni_pipeline_metrics.claude_calls         + EXCLUDED.claude_calls,
            claude_input_tokens  = omni_pipeline_metrics.claude_input_tokens  + EXCLUDED.claude_input_tokens,
            claude_output_tokens = omni_pipeline_metrics.claude_output_tokens + EXCLUDED.claude_output_tokens,
            total_cost           = omni_pipeline_metrics.total_cost           + EXCLUDED.total_cost,
            completed_at         = COALESCE(EXCLUDED.completed_at, omni_pipeline_metrics.completed_at)
        """,
        env["entity_id"],
        env["workspace_id"],
        p.get("collector_source"),
        int(p.get("companies_collected") or 0),
        int(p.get("companies_qualified") or 0),
        int(p.get("companies_rejected") or 0),
        int(p.get("people_found") or 0),
        int(p.get("people_verified") or 0),
        int(p.get("leads_created") or 0),
        int(p.get("serper_calls") or 0),
        int(p.get("claude_calls") or 0),
        int(p.get("claude_input_tokens") or 0),
        int(p.get("claude_output_tokens") or 0),
        float(p.get("total_cost") or 0),
        datetime.fromisoformat(env["occurred_at"]) if kind == "end" else None,
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
    # PROJ-002: messages are an append-only log, so this projector keys on the
    # EVENT id (env["id"]) rather than an entity_id like the upsert projectors
    # (_project_contact/company/lead). Two message events never share an id, so
    # ON CONFLICT (id) DO NOTHING is pure idempotency for redelivery — there is
    # deliberately no message "correction"/update path. If message editing is
    # ever needed, switch to an entity_id key + an UPDATE branch.
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


async def _project_email_tracking(env: dict[str, Any]) -> None:
    """T3: append-only open/click log. Keyed on the EVENT id (like messages) so
    redelivery is idempotent — every hit is its own row."""
    p = env.get("payload") or {}
    await execute(
        """
        INSERT INTO omni_email_tracking (id, workspace_id, lead_id, contact_id,
                                         event_type, url, occurred_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        ON CONFLICT (id) DO NOTHING
        """,
        env["id"],
        env["workspace_id"],
        p.get("lead_id"),
        p.get("contact_id"),
        p.get("kind") or ("click" if env["event_type"] == "email.clicked" else "open"),
        p.get("url"),
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
    "task": _project_task,  # CONTRACT-004
}


async def _project_lead_outcome(env: dict[str, Any]) -> None:
    """H1: record a lead's terminal outcome from flow.goal / flow.end.

    flow.goal emits ``lead.goal_reached`` {goal_name, value}; flow.end emits
    ``lead.sequence_ended`` {reason}. The transition worker already set the lead's
    status (converted / ended); here we persist the outcome detail into
    custom_fields so Analytics can attribute conversions (goal_name + value) and
    explain dead-ends (reason). Keyed by entity_id (the lead)."""
    p = env.get("payload") or {}
    et = env["event_type"]
    if et == "lead.goal_reached":
        outcome = {
            "kind": "converted",
            "goal_name": p.get("goal_name"),
            "value": p.get("value"),
            "at": env.get("occurred_at"),
        }
        status = "converted"
    else:  # lead.sequence_ended
        outcome = {"kind": "ended", "reason": p.get("reason"), "at": env.get("occurred_at")}
        status = "ended"
    await execute(
        """
        UPDATE omni_leads
           SET custom_fields = COALESCE(custom_fields, '{}'::jsonb) || jsonb_build_object('outcome', $1::jsonb),
               status = $2,
               updated_at = NOW()
         WHERE id = $3 AND workspace_id = $4
        """,
        json.dumps(outcome),
        status,
        env["entity_id"],
        env["workspace_id"],
    )


# Entity deletion: a `<entity>.deleted` event removes the projection row. This
# keeps the read side write-free (mutation = event) while giving the CRM a real
# delete. The event stays in events_archive (audit), only the projection drops.
# Companies cascade their KG side-tables (aliases + cached people) so a re-run
# rediscovers them cleanly instead of hitting a stale `known` cache.
_DELETE_TABLE = {
    "contact": ("omni_contacts",),
    "company": ("omni_companies", "omni_company_aliases", "omni_people_cache"),
    "deal": ("omni_deals",),
    "lead": ("omni_leads",),
}


async def _project_delete(env: dict[str, Any]) -> None:
    entity = env["entity_type"]
    tables = _DELETE_TABLE.get(entity)
    if not tables or not env.get("entity_id"):
        return
    primary, *cascades = tables
    # cascade side-tables first (FK-free, keyed by company_id), then the row.
    for tbl in cascades:
        col = "company_id" if entity == "company" else "id"
        await execute(
            f"DELETE FROM {tbl} WHERE {col} = $1 AND workspace_id = $2",
            env["entity_id"],
            env["workspace_id"],
        )
    await execute(
        f"DELETE FROM {primary} WHERE id = $1 AND workspace_id = $2",
        env["entity_id"],
        env["workspace_id"],
    )


async def _apply_projection(env: dict[str, Any]) -> None:
    et = env["event_type"]
    entity = env["entity_type"]
    if et.endswith(".deleted") and env.get("entity_id"):
        await _project_delete(env)
        return
    if et in ("message.received", "message.sent"):
        await _project_message(env)
        return
    # T3: email engagement (open/click) — append-only tracking log.
    if et in ("email.opened", "email.clicked"):
        await _project_email_tracking(env)
        return
    # H1: terminal lead outcomes (conversion vs dead-end) carry detail the
    # generic lead projector would drop. Handle before the entity dispatch.
    if et in ("lead.goal_reached", "lead.sequence_ended") and env.get("entity_id"):
        await _project_lead_outcome(env)
        return
    # AI lifecycle events feed two projections: the job log (always) and,
    # for completed scores, the per-lead score table.
    if et.startswith("ai."):
        await _project_ai_job(env)
        if et == "ai.score.completed" and env.get("entity_id"):
            await _project_lead_score(env)
        return
    # CONTRACT-005: approvals queue (request -> draft-edit -> resolved), keyed
    # by lead id. B1 adds approval.draft_updated for AI draft-review.
    if et in ("approval.requested", "approval.draft_updated", "approval.resolved") and env.get("entity_id"):
        await _project_approval(env)
        return
    # Pipeline cost/usage metrics (per source run). entity_id = run_id.
    if et == "pipeline.metric" and env.get("entity_id"):
        await _project_pipeline_metric(env)
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
            # PROJ-001: apply the projection BEFORE archiving, so a transient
            # projection failure leaves the offset uncommitted and the record is
            # redelivered with the projection re-attempted. All projections are
            # idempotent upserts (ON CONFLICT), so re-applying on redelivery is
            # safe. Gating projection on the archive's first-insert (the old
            # `if inserted`) meant a post-archive projection failure would, on
            # redelivery, hit ON CONFLICT DO NOTHING and silently skip the
            # projection forever. Archive is now the durable commit-point that
            # marks "projected".
            await _apply_projection(env)
            await _archive_event(env, rec)
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
