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
from app.execution import lead_columns

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
    # Display-layer derivation (a lead's columns are additive per workflow; see
    # app.execution.lead_columns). identity/stage are computed; ``fields`` is the
    # flattened bag the dynamic-column table reads, keyed by ColumnSpec.key.
    identity: str
    stage: str
    fields: dict[str, Any]


class LeadColumnOut(BaseModel):
    key: str
    label: str
    path: str
    kind: str


class LeadColumnsResponse(BaseModel):
    """Column descriptor for the (optionally workflow-scoped) Leads table.
    Frontend renders the table header + cell accessors from this."""

    workflow_id: uuid.UUID | None
    columns: list[LeadColumnOut]


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


async def _workflow_node_types(workflow_id: uuid.UUID | None) -> set[str]:
    """The set of node_types a workflow contains — drives which columns its
    leads can populate. Empty set for the "All workflows" view."""
    if not workflow_id:
        return set()
    rows = await fetch_all(
        "SELECT DISTINCT node_type FROM omni_workflow_nodes WHERE workflow_id = $1", workflow_id
    )
    return {r["node_type"] for r in rows}


@router.get(
    "/leads/columns",
    response_model=LeadColumnsResponse,
    summary="Columns for the (optionally workflow-scoped) Leads table",
    description=(
        "A lead's displayable fields are additive per node, so the column set is "
        "derived from the workflow's node graph. With no workflow_id (the 'All "
        "workflows' view) only the universal identity/stage/status/updated "
        "columns apply."
    ),
)
async def lead_columns_for_workflow(
    _: AuthContext = Depends(get_current_workspace),
    workflow_id: uuid.UUID | None = Query(None),
) -> LeadColumnsResponse:
    node_types = await _workflow_node_types(workflow_id)
    cols = lead_columns.derive_columns(node_types)
    return LeadColumnsResponse(
        workflow_id=workflow_id,
        columns=[LeadColumnOut(key=c.key, label=c.label, path=c.path, kind=c.kind) for c in cols],
    )


@router.get("/leads", response_model=list[LeadOut], summary="List leads, with contact identity joined and per-workflow display fields")
async def list_leads(
    _: AuthContext = Depends(get_current_workspace),
    workflow_id: uuid.UUID | None = Query(None),
    limit: int = Query(500, ge=1, le=5000),
) -> list[LeadOut]:
    # LEFT JOIN the contact so the view can show a name/company/title/email for
    # person-stage leads. Company-stage leads (no contact) read their identity
    # and columns from custom_fields (the per-item company row). Contact columns
    # are namespaced c_* and folded into a synthetic ``contact`` sub-object on
    # the field bag so ColumnSpec paths like ``contact.company`` resolve.
    select = """
        SELECT l.id, l.contact_id, l.workflow_id, l.current_node_id, l.status,
               l.custom_fields, l.created_at, l.updated_at,
               c.first_name AS c_first_name, c.last_name AS c_last_name,
               c.email AS c_email, c.company AS c_company, c.headline AS c_headline,
               c.linkedin_url AS c_linkedin_url, c.phone AS c_phone
        FROM omni_leads l
        LEFT JOIN omni_contacts c ON c.id = l.contact_id AND c.workspace_id = l.workspace_id
    """
    if workflow_id:
        rows = await fetch_all(
            select + " WHERE l.workflow_id = $1 ORDER BY l.updated_at DESC LIMIT $2", workflow_id, limit
        )
    else:
        rows = await fetch_all(select + " ORDER BY l.updated_at DESC LIMIT $1", limit)

    columns = lead_columns.derive_columns(await _workflow_node_types(workflow_id))
    return [_lead_out(dict(r), columns) for r in rows]


def _lead_out(row: dict[str, Any], columns: list[lead_columns.ColumnSpec]) -> LeadOut:
    """Build a LeadOut: fold the joined contact into a ``contact`` sub-object,
    compute identity/stage, and flatten each derived column into ``fields``."""
    custom_fields = row.get("custom_fields") or {}
    contact = None
    if row.get("contact_id"):
        contact = {
            "first_name": row.get("c_first_name"),
            "last_name": row.get("c_last_name"),
            "email": row.get("c_email"),
            "company": row.get("c_company"),
            "headline": row.get("c_headline"),
            "linkedin_url": row.get("c_linkedin_url"),
            "phone": row.get("c_phone"),
        }
        name = " ".join(p for p in (contact["first_name"], contact["last_name"]) if p).strip()
        contact["name"] = name or contact.get("email")

    lead_id = str(row["id"])
    identity = lead_columns.lead_identity(custom_fields, contact, lead_id)
    stage = lead_columns.lead_stage(custom_fields, has_contact=contact is not None)

    # The field bag every ColumnSpec.path resolves against: custom_fields plus a
    # synthetic ``contact`` sub-object plus the universal top-level fields.
    bag: dict[str, Any] = dict(custom_fields)
    if contact is not None:
        bag["contact"] = contact
    bag["identity"] = identity
    bag["stage"] = stage
    bag["status"] = row["status"]
    bag["updated_at"] = row["updated_at"].isoformat() if row.get("updated_at") else None

    fields = {c.key: lead_columns.resolve_path(bag, c.path) for c in columns}

    return LeadOut(
        id=row["id"],
        contact_id=row.get("contact_id"),
        workflow_id=row.get("workflow_id"),
        current_node_id=row.get("current_node_id"),
        status=row["status"],
        custom_fields=custom_fields,
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        identity=identity,
        stage=stage,
        fields=fields,
    )
