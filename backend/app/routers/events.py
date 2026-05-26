"""Append-only event log API.

The events table is the v2 spine: every CRM entity is a projection over it,
every node execution emits events here, every audit trail starts here.
This router exposes minimal surface — append + filtered read — because
mutation belongs to nodes, not to operators with curl.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import fetch_all

router = APIRouter()


class EventCreate(BaseModel):
    event_type: str = Field(min_length=1, max_length=120, description="Dotted name, e.g. 'contact.created' or 'deal.stage_changed'")
    entity_type: str = Field(min_length=1, max_length=60, description="The entity this event belongs to (contact, company, deal, lead, workflow, …)")
    entity_id: uuid.UUID | None = Field(None, description="Subject of the event; null for workspace-level events")
    payload: dict[str, Any] = Field(default_factory=dict, description="Free-form JSON payload — keep small and well-typed by convention")
    correlation_id: uuid.UUID | None = Field(None, description="Threads related events together (e.g. a node execution + its result)")


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
    status_code=201,
    summary="Append an event to the log",
    description="Appends a single immutable event to the workspace's event log. Returns the persisted row with its generated id and timestamp.",
)
async def append_event(body: EventCreate, ctx: AuthContext = Depends(get_current_workspace)) -> EventOut:
    row = await fetch_all(
        """
        INSERT INTO events (workspace_id, event_type, entity_type, entity_id, payload, actor_user_id, correlation_id)
        VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7)
        RETURNING id, workspace_id, event_type, entity_type, entity_id, payload, actor_user_id, correlation_id, occurred_at
        """,
        ctx.workspace_id,
        body.event_type,
        body.entity_type,
        body.entity_id,
        body.payload,
        ctx.user_id,
        body.correlation_id,
    )
    return EventOut.model_validate(row[0])


@router.get(
    "",
    response_model=list[EventOut],
    summary="Stream the event log (filterable)",
    description="Returns events most-recent-first. Filterable by entity_type, entity_id, event_type, correlation_id, and time window.",
)
async def list_events(
    ctx: AuthContext = Depends(get_current_workspace),
    entity_type: str | None = Query(None),
    entity_id: uuid.UUID | None = Query(None),
    event_type: str | None = Query(None, description="Prefix-match on event_type ('contact.' matches every contact event)"),
    correlation_id: uuid.UUID | None = Query(None),
    since: datetime | None = Query(None, description="Only events at or after this timestamp"),
    until: datetime | None = Query(None, description="Only events strictly before this timestamp"),
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
        FROM events
        WHERE {' AND '.join(clauses)}
        ORDER BY occurred_at DESC
        LIMIT ${len(args)}
        """,
        *args,
    )
    return [EventOut.model_validate(r) for r in rows]
