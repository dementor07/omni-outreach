"""Event API.

  POST /events  publishes one event onto Redpanda (omni.events). Returns
                the envelope as published; durable persistence happens
                asynchronously when the projector reads the message.
  GET  /events  reads the historical event log from the `events_archive`
                projection table. Filterable by entity, type, correlation,
                and time window.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import fetch_all
from app.services.bus import publish_event

router = APIRouter()

# EVT-001: POST /events writes to the durable log and the projector applies it
# faithfully, so an unrestricted endpoint lets any authed user fabricate
# projected state in their own tenant (fake lead scores, forged completions,
# spoofed sequence-ended). Only allow event_types a human is meant to author by
# hand — CRM mutations and manual notes. Everything else (ai.*, *.queued,
# *.completed, *.requested, lead.sequence_ended, …) is worker-produced and must
# not be injectable through this endpoint.
_USER_PUBLISHABLE_EVENT_TYPES: frozenset[str] = frozenset(
    {
        "contact.created",
        "contact.updated",
        "company.created",
        "company.updated",
        "deal.created",
        "deal.updated",
        "deal.stage_changed",
        "note.added",
    }
)


def _assert_user_publishable(event_type: str) -> None:
    if event_type not in _USER_PUBLISHABLE_EVENT_TYPES:
        raise HTTPException(
            status_code=403,
            detail=(
                f"event_type {event_type!r} is not user-publishable; "
                "worker-only events cannot be injected via this endpoint"
            ),
        )


class EventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=120, description="Dotted name, e.g. 'contact.created' or 'deal.stage_changed'")
    entity_type: str = Field(min_length=1, max_length=60, description="The entity this event belongs to (contact, company, deal, lead, workflow, …)")
    entity_id: uuid.UUID | None = Field(None, description="Subject of the event; null for workspace-level events")
    payload: dict[str, Any] = Field(default_factory=dict, description="Free-form JSON payload")
    correlation_id: uuid.UUID | None = Field(None, description="Threads related events together")


class EventOut(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    event_type: str
    entity_type: str
    entity_id: uuid.UUID | None
    payload: dict[str, Any]
    actor_user_id: uuid.UUID | None
    correlation_id: uuid.UUID | None
    occurred_at: datetime


@router.post(
    "",
    response_model=EventOut,
    status_code=202,
    summary="Publish an event",
    description=(
        "Publishes one event onto the omni.events Redpanda topic. Returns "
        "the envelope; the projector worker writes it to events_archive "
        "and updates projection tables asynchronously. Status 202 because "
        "durable persistence is asynchronous."
    ),
)
async def append_event(body: EventCreate, ctx: AuthContext = Depends(get_current_workspace)) -> EventOut:
    _assert_user_publishable(body.event_type)
    env = await publish_event(
        workspace_id=ctx.workspace_id,
        event_type=body.event_type,
        entity_type=body.entity_type,
        entity_id=str(body.entity_id) if body.entity_id else None,
        payload=body.payload,
        actor_user_id=ctx.user_id,
        correlation_id=str(body.correlation_id) if body.correlation_id else None,
    )
    return EventOut.model_validate(env)


@router.get(
    "",
    response_model=list[EventOut],
    summary="Query the historical event log",
    description=(
        "Reads from the events_archive projection (built by the projector "
        "worker from omni.events). Most-recent-first; filterable by entity, "
        "event_type prefix, correlation_id, and time window."
    ),
)
async def list_events(
    ctx: AuthContext = Depends(get_current_workspace),
    entity_type: str | None = Query(None),
    entity_id: uuid.UUID | None = Query(None),
    event_type: str | None = Query(None, description="Prefix-match if it ends with a dot ('contact.' matches every contact event)"),
    correlation_id: uuid.UUID | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
) -> list[EventOut]:
    clauses = ["workspace_id = $1"]
    args: list[Any] = [ctx.workspace_id]
    if entity_type:
        clauses.append(f"entity_type = ${len(args) + 1}")
        args.append(entity_type)
    if entity_id:
        clauses.append(f"entity_id = ${len(args) + 1}")
        args.append(entity_id)
    if event_type:
        clauses.append(f"event_type LIKE ${len(args) + 1}")
        args.append(event_type if not event_type.endswith(".") else f"{event_type}%")
    if correlation_id:
        clauses.append(f"correlation_id = ${len(args) + 1}")
        args.append(correlation_id)
    if since:
        clauses.append(f"occurred_at >= ${len(args) + 1}")
        args.append(since)
    if until:
        clauses.append(f"occurred_at < ${len(args) + 1}")
        args.append(until)
    args.append(limit)
    rows = await fetch_all(
        f"""
        SELECT id, workspace_id, event_type, entity_type, entity_id, payload,
               actor_user_id, correlation_id, occurred_at
        FROM omni_events_archive
        WHERE {' AND '.join(clauses)}
        ORDER BY occurred_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )
    return [EventOut.model_validate(r) for r in rows]
