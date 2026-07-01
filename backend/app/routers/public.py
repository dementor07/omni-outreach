"""Public action API — `/public/v1/*` (N8N-001 Part 1d).

The customer-facing, versioned, documented surface an external system (n8n,
Zapier, a customer's own backend) calls with an API key. Every route:

  * depends on ``get_workspace_any`` (API key OR JWT) — the workspace is resolved
    ONLY from the credential, never from the request body, and RLS is the tenant
    boundary;
  * is a THIN wrapper over the same internal logic the dashboard uses — no
    business logic is duplicated here;
  * carries an OpenAPI summary + example so it renders cleanly in `/docs`.

The write actions (`enrich`, `leads/find`) publish the SAME intent/job event the
in-canvas node emits onto the durable event log and return a correlation id the
caller can trace — they do not re-implement the provider call.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext
from app.auth_apikey import get_workspace_any
from app.db import fetch_all, fetch_one, system_scope
from app.services import bus

router = APIRouter()


# ── Contacts ──────────────────────────────────────────────────────────────────


class PublicContactCreate(BaseModel):
    email: str | None = Field(None, examples=["ada@example.com"])
    linkedin_url: str | None = Field(None, examples=["https://linkedin.com/in/ada"])
    first_name: str | None = Field(None, examples=["Ada"])
    last_name: str | None = Field(None, examples=["Lovelace"])
    company: str | None = Field(None, examples=["Analytical Engines"])
    headline: str | None = Field(None, examples=["Founder"])
    phone: str | None = None
    source: str = Field("api", examples=["api"])


@router.post(
    "/contacts",
    status_code=201,
    summary="Add a contact to the CRM",
    description=(
        "Create or upsert one contact. The id is deterministic (UUIDv5 of "
        "workspace + linkedin/email) so re-adding the same person converges on "
        "one row. Requires an email or a linkedin_url."
    ),
)
async def create_contact(
    body: PublicContactCreate, ctx: AuthContext = Depends(get_workspace_any)
) -> dict[str, Any]:
    # Reuse the internal add-contact path verbatim (deterministic id + emit).
    from app.routers.projections import ContactCreate
    from app.routers.projections import create_contact as _internal_create

    if not body.email and not body.linkedin_url:
        raise HTTPException(status_code=422, detail="a contact needs an email or a linkedin_url")
    out = await _internal_create(ContactCreate(**body.model_dump()), ctx)
    return out.model_dump(mode="json")


@router.get(
    "/contacts",
    summary="List contacts (paginated)",
    description="Reads are RLS-scoped to the API key's workspace.",
)
async def list_contacts(
    _: AuthContext = Depends(get_workspace_any),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows = await fetch_all(
        "SELECT id, email, first_name, last_name, company, headline, linkedin_url, "
        "phone, source, created_at FROM omni_contacts "
        "ORDER BY created_at DESC LIMIT $1 OFFSET $2",
        limit, offset,
    )
    total_row = await fetch_one("SELECT COUNT(*) AS n FROM omni_contacts")
    return {
        "data": [_jsonable(r) for r in rows],
        "meta": {"total": total_row["n"] if total_row else 0, "limit": limit, "offset": offset},
    }


# ── Leads ─────────────────────────────────────────────────────────────────────


@router.get(
    "/leads",
    summary="List leads (paginated)",
    description="Reads are RLS-scoped to the API key's workspace.",
)
async def list_leads(
    _: AuthContext = Depends(get_workspace_any),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    rows = await fetch_all(
        "SELECT id, contact_id, workflow_id, status, current_node_id, created_at, updated_at "
        "FROM omni_leads ORDER BY updated_at DESC LIMIT $1 OFFSET $2",
        limit, offset,
    )
    total_row = await fetch_one("SELECT COUNT(*) AS n FROM omni_leads")
    return {
        "data": [_jsonable(r) for r in rows],
        "meta": {"total": total_row["n"] if total_row else 0, "limit": limit, "offset": offset},
    }


class LeadFind(BaseModel):
    finder_type: str = Field("leads_finder_ai", examples=["leads_finder_ai"])
    input_data: str = Field(examples=["Heads of Growth at Series-B fintechs in the UK"])
    fetch_count: int = Field(25, ge=1, le=100)
    connection_name: str = Field(examples=["linkfinder"])


@router.post(
    "/leads/find",
    status_code=202,
    summary="Queue a LinkFinder people-discovery run",
    description=(
        "Enqueues a `source.leads_finder.requested` event with the same shape the "
        "in-canvas LinkFinder source emits. Returns a correlation id to trace the "
        "run. Discovered people appear via the Leads view / `GET /public/v1/leads`."
    ),
)
async def find_leads(
    body: LeadFind, ctx: AuthContext = Depends(get_workspace_any)
) -> dict[str, Any]:
    correlation_id = str(uuid.uuid4())
    await bus.publish_event(
        workspace_id=str(ctx.workspace_id),
        event_type="source.leads_finder.requested",
        entity_type="workflow",
        entity_id=None,
        payload={
            "provider": "linkfinder",
            "connection_name": body.connection_name,
            "linkfinder_type": body.finder_type,
            "input_data": body.input_data,
            "fetch_count": body.fetch_count,
            "correlation_id": correlation_id,
            "source": "public_api",
        },
        actor_user_id=ctx.user_id or None,
        correlation_id=correlation_id,
    )
    return {"accepted": True, "correlation_id": correlation_id}


class EnrichRequest(BaseModel):
    lead: dict[str, Any] = Field(examples=[{"email": "ada@example.com"}])
    enrich_source: str = Field("apollo", examples=["apollo"])
    linkfinder_type: str | None = None
    connection_name: str = Field(examples=["apollo"])


@router.post(
    "/enrich",
    status_code=202,
    summary="Queue a one-off enrichment",
    description=(
        "Enqueues an `ai.enrich.requested` event with the same shape the in-canvas "
        "enrichment node emits, for a one-off lead payload. Returns a correlation id."
    ),
)
async def enrich(
    body: EnrichRequest, ctx: AuthContext = Depends(get_workspace_any)
) -> dict[str, Any]:
    correlation_id = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "enrich_source": body.enrich_source,
        "connection_name": body.connection_name,
        "lead": body.lead,
        "correlation_id": correlation_id,
        "source": "public_api",
    }
    if body.linkfinder_type:
        payload["linkfinder_type"] = body.linkfinder_type
    await bus.publish_event(
        workspace_id=str(ctx.workspace_id),
        event_type="ai.enrich.requested",
        entity_type="lead",
        entity_id=None,
        payload=payload,
        actor_user_id=ctx.user_id or None,
        correlation_id=correlation_id,
    )
    return {"accepted": True, "correlation_id": correlation_id}


# ── Campaigns ─────────────────────────────────────────────────────────────────


@router.post(
    "/campaigns/{campaign_id}/run",
    summary="Run a campaign",
    description="Triggers a run of the given workflow — the same trigger the dashboard's Run button uses.",
)
async def run_campaign(
    campaign_id: uuid.UUID, ctx: AuthContext = Depends(get_workspace_any)
) -> dict[str, Any]:
    # Reuse the internal run trigger verbatim.
    from app.routers.canvas import RunRequest
    from app.routers.canvas import run_workflow as _internal_run

    resp = await _internal_run(campaign_id, RunRequest(), ctx)
    return resp.model_dump(mode="json")


def _jsonable(row: dict[str, Any]) -> dict[str, Any]:
    """Coerce UUID/datetime values to JSON-serialisable primitives for the reads."""
    out: dict[str, Any] = {}
    for k, v in row.items():
        if isinstance(v, uuid.UUID):
            out[k] = str(v)
        elif hasattr(v, "isoformat"):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out
