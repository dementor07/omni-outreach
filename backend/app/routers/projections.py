"""Read-only projections over the event log.

Every CRM entity surface — contacts, companies, deals, leads, activity —
is a SELECT over ``events`` via the views created in migration 021. This
router is the thin HTTP layer over those views; no writes ever happen
here. Mutation is emitting events.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from app.auth import AuthContext, get_current_workspace
from app.db import fetch_all

router = APIRouter()


class ContactOut(BaseModel):
    id: uuid.UUID
    email: str | None
    first_name: str | None
    last_name: str | None
    company: str | None
    headline: str | None
    linkedin_url: str | None
    phone: str | None
    latest_payload: dict[str, Any]
    created_at: datetime | None
    updated_at: datetime


class CompanyOut(BaseModel):
    id: uuid.UUID
    name: str | None
    domain: str | None
    industry: str | None
    size: str | None
    latest_payload: dict[str, Any]
    updated_at: datetime


class DealOut(BaseModel):
    id: uuid.UUID
    name: str | None
    stage: str | None
    value: Decimal | None
    currency: str | None
    contact_id: uuid.UUID | None
    company_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    close_date: datetime | None
    latest_payload: dict[str, Any]
    updated_at: datetime


class LeadOut(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID | None
    workflow_id: uuid.UUID | None
    current_node_id: uuid.UUID | None
    status: str | None
    latest_payload: dict[str, Any]
    updated_at: datetime


class ActivityOut(BaseModel):
    id: uuid.UUID
    event_type: str
    entity_type: str
    entity_id: uuid.UUID | None
    payload: dict[str, Any]
    actor_user_id: uuid.UUID | None
    occurred_at: datetime


@router.get(
    "/contacts",
    response_model=list[ContactOut],
    summary="List contacts in this workspace",
    description="Read-only projection over the event log. Returns the latest snapshot per contact.",
)
async def list_contacts(
    _: AuthContext = Depends(get_current_workspace),
    limit: int = Query(100, ge=1, le=500),
) -> list[ContactOut]:
    rows = await fetch_all("SELECT * FROM contacts_v ORDER BY updated_at DESC LIMIT $1", limit)
    return [ContactOut.model_validate(r) for r in rows]


@router.get("/companies", response_model=list[CompanyOut], summary="List companies in this workspace")
async def list_companies(
    _: AuthContext = Depends(get_current_workspace),
    limit: int = Query(100, ge=1, le=500),
) -> list[CompanyOut]:
    rows = await fetch_all("SELECT * FROM companies_v ORDER BY updated_at DESC LIMIT $1", limit)
    return [CompanyOut.model_validate(r) for r in rows]


@router.get("/deals", response_model=list[DealOut], summary="List deals in this workspace (Kanban source)")
async def list_deals(
    _: AuthContext = Depends(get_current_workspace),
    stage: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
) -> list[DealOut]:
    if stage:
        rows = await fetch_all("SELECT * FROM deals_v WHERE stage = $1 ORDER BY updated_at DESC LIMIT $2", stage, limit)
    else:
        rows = await fetch_all("SELECT * FROM deals_v ORDER BY updated_at DESC LIMIT $1", limit)
    return [DealOut.model_validate(r) for r in rows]


@router.get("/leads", response_model=list[LeadOut], summary="List leads currently inside workflows")
async def list_leads(
    _: AuthContext = Depends(get_current_workspace),
    workflow_id: uuid.UUID | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
) -> list[LeadOut]:
    if workflow_id:
        rows = await fetch_all("SELECT * FROM leads_v WHERE workflow_id = $1 ORDER BY updated_at DESC LIMIT $2", workflow_id, limit)
    else:
        rows = await fetch_all("SELECT * FROM leads_v ORDER BY updated_at DESC LIMIT $1", limit)
    return [LeadOut.model_validate(r) for r in rows]


@router.get("/activity", response_model=list[ActivityOut], summary="Unified activity timeline")
async def list_activity(
    _: AuthContext = Depends(get_current_workspace),
    entity_id: uuid.UUID | None = Query(None, description="Filter to one entity's timeline"),
    limit: int = Query(200, ge=1, le=1000),
) -> list[ActivityOut]:
    if entity_id:
        rows = await fetch_all("SELECT * FROM activity_v WHERE entity_id = $1 LIMIT $2", entity_id, limit)
    else:
        rows = await fetch_all("SELECT * FROM activity_v LIMIT $1", limit)
    return [ActivityOut.model_validate(r) for r in rows]
