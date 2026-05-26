"""Read-only projection API.

Every projection table (contacts, companies, deals, leads, messages) is
maintained by the projector worker reading omni.events. This router is
the thin HTTP layer over the read side — no writes ever happen here.
Mutation = publishing an event.
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
    source: str | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CompanyOut(BaseModel):
    id: uuid.UUID
    name: str
    domain: str | None
    industry: str | None
    size: str | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DealOut(BaseModel):
    id: uuid.UUID
    name: str
    stage: str
    value: Decimal | None
    currency: str
    contact_id: uuid.UUID | None
    company_id: uuid.UUID | None
    owner_user_id: uuid.UUID | None
    close_date: datetime | None
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class LeadOut(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID | None
    workflow_id: uuid.UUID | None
    current_node_id: uuid.UUID | None
    status: str
    custom_fields: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@router.get("/contacts", response_model=list[ContactOut], summary="List contacts in this workspace")
async def list_contacts(_: AuthContext = Depends(get_current_workspace), limit: int = Query(100, ge=1, le=500)) -> list[ContactOut]:
    rows = await fetch_all("SELECT * FROM omni_contacts ORDER BY updated_at DESC LIMIT $1", limit)
    return [ContactOut.model_validate(r) for r in rows]


@router.get("/companies", response_model=list[CompanyOut], summary="List companies in this workspace")
async def list_companies(_: AuthContext = Depends(get_current_workspace), limit: int = Query(100, ge=1, le=500)) -> list[CompanyOut]:
    rows = await fetch_all("SELECT * FROM omni_companies ORDER BY updated_at DESC LIMIT $1", limit)
    return [CompanyOut.model_validate(r) for r in rows]


@router.get("/deals", response_model=list[DealOut], summary="List deals (Kanban source)")
async def list_deals(
    _: AuthContext = Depends(get_current_workspace),
    stage: str | None = Query(None),
    limit: int = Query(500, ge=1, le=2000),
) -> list[DealOut]:
    if stage:
        rows = await fetch_all("SELECT * FROM omni_deals WHERE stage = $1 ORDER BY updated_at DESC LIMIT $2", stage, limit)
    else:
        rows = await fetch_all("SELECT * FROM omni_deals ORDER BY updated_at DESC LIMIT $1", limit)
    return [DealOut.model_validate(r) for r in rows]


@router.get("/leads", response_model=list[LeadOut], summary="List leads currently inside workflows")
async def list_leads(
    _: AuthContext = Depends(get_current_workspace),
    workflow_id: uuid.UUID | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
) -> list[LeadOut]:
    if workflow_id:
        rows = await fetch_all("SELECT * FROM omni_leads WHERE workflow_id = $1 ORDER BY updated_at DESC LIMIT $2", workflow_id, limit)
    else:
        rows = await fetch_all("SELECT * FROM omni_leads ORDER BY updated_at DESC LIMIT $1", limit)
    return [LeadOut.model_validate(r) for r in rows]
