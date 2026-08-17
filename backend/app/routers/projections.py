"""Read-only projection API.

Every projection table (contacts, companies, deals, leads, messages) is
maintained by the projector worker reading omni.events. This router is
the thin HTTP layer over the read side — no writes ever happen here.
Mutation = publishing an event.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import fetch_all, fetch_one, system_scope
from app.execution import lead_columns
from app.services.bus import publish_event

router = APIRouter()


async def _delete_entity(ctx: AuthContext, *, table: str, entity_type: str, entity_id: uuid.UUID) -> None:
    """Delete a CRM projection row by publishing a ``<entity>.deleted`` event.

    The read side never writes (mutation = event): the projector applies the
    deletion (and cascades company KG side-tables). 404 if the row isn't in this
    workspace so a stale id can't silently no-op. RLS already scopes the lookup."""
    row = await fetch_one(f"SELECT id FROM {table} WHERE id = $1", entity_id)
    if not row:
        raise HTTPException(status_code=404, detail=f"{entity_type} not found")
    await publish_event(
        workspace_id=ctx.workspace_id,
        event_type=f"{entity_type}.deleted",
        entity_type=entity_type,
        entity_id=str(entity_id),
        payload={"deleted_by": ctx.user_id},
        actor_user_id=ctx.user_id,
    )


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
    status_reason: str | None = None


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


class ContactSummary(BaseModel):
    total: int
    with_email: int
    with_linkedin: int
    with_company: int


class LeadSummary(BaseModel):
    total: int
    active: int
    people: int
    companies: int
    hot: int


def _contact_filters(
    q: str | None,
    source: str | None,
    workflow_id: uuid.UUID | None,
    has_email: bool | None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []

    if q and q.strip():
        args.append(f"%{q.strip()}%")
        i = len(args)
        clauses.append(
            f"(c.first_name ILIKE ${i} OR c.last_name ILIKE ${i} OR c.email ILIKE ${i} "
            f"OR c.company ILIKE ${i} OR c.headline ILIKE ${i})"
        )
    if source:
        args.append(source)
        clauses.append(f"c.source = ${len(args)}")
    if has_email is True:
        clauses.append("c.email IS NOT NULL AND c.email <> ''")
    elif has_email is False:
        clauses.append("(c.email IS NULL OR c.email = '')")
    if workflow_id:
        args.append(workflow_id)
        clauses.append(
            f"EXISTS (SELECT 1 FROM omni_leads l WHERE l.contact_id = c.id AND l.workflow_id = ${len(args)})"
        )

    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), args


@router.get("/contacts", response_model=list[ContactOut], summary="List contacts, with filters")
async def list_contacts(
    _: AuthContext = Depends(get_current_workspace),
    q: str | None = Query(None, description="Search across name, email, company, title"),
    source: str | None = Query(None, description="Filter by acquisition source (e.g. naukri, greenhouse)"),
    workflow_id: uuid.UUID | None = Query(None, description="Only contacts enrolled in this campaign (via a lead)"),
    has_email: bool | None = Query(None, description="True = only contacts with an email"),
    limit: int = Query(100, ge=1, le=500),
) -> list[ContactOut]:
    where, args = _contact_filters(q, source, workflow_id, has_email)
    args.append(limit)
    rows = await fetch_all(
        f"SELECT c.* FROM omni_contacts c {where} ORDER BY c.updated_at DESC LIMIT ${len(args)}",
        *args,
    )
    return [ContactOut.model_validate(r) for r in rows]


@router.get(
    "/contacts/summary",
    response_model=ContactSummary,
    summary="Exact contact counts for the current filters",
)
async def contact_summary(
    _: AuthContext = Depends(get_current_workspace),
    q: str | None = Query(None),
    source: str | None = Query(None),
    workflow_id: uuid.UUID | None = Query(None),
    has_email: bool | None = Query(None),
) -> ContactSummary:
    where, args = _contact_filters(q, source, workflow_id, has_email)
    row = await fetch_one(
        f"""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE c.email IS NOT NULL AND c.email <> '') AS with_email,
            COUNT(*) FILTER (WHERE c.linkedin_url IS NOT NULL AND c.linkedin_url <> '') AS with_linkedin,
            COUNT(*) FILTER (WHERE c.company IS NOT NULL AND c.company <> '') AS with_company
        FROM omni_contacts c
        {where}
        """,
        *args,
    )
    return ContactSummary(**{k: int((row or {}).get(k) or 0) for k in ContactSummary.model_fields})


# NB: static /contacts/* paths are declared BEFORE /contacts/{contact_id}
# so they can never be shadowed by the dynamic segment.
@router.get(
    "/contacts/sources",
    response_model=list[str],
    summary="Distinct contact sources (for the source filter dropdown)",
)
async def contact_sources(_: AuthContext = Depends(get_current_workspace)) -> list[str]:
    rows = await fetch_all(
        "SELECT DISTINCT source FROM omni_contacts WHERE source IS NOT NULL AND source <> '' ORDER BY source"
    )
    return [r["source"] for r in rows]


@router.get("/contacts/{contact_id}", response_model=ContactOut, summary="Fetch one contact")
async def get_contact(
    contact_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)
) -> ContactOut:
    row = await fetch_one("SELECT * FROM omni_contacts WHERE id = $1", contact_id)
    if not row:
        raise HTTPException(status_code=404, detail="contact not found")
    return ContactOut.model_validate(row)


class ScreenIcpRequest(BaseModel):
    prompt: str = Field(min_length=10, description="ICP rubric; a contact is marked icp_qualified when it matches this")
    batch_size: int = Field(60, ge=10, le=120, description="Contacts per LLM call")
    concurrency: int = Field(6, ge=1, le=12, description="Parallel LLM calls")


class ScreenIcpResult(BaseModel):
    screened: int
    qualified: int


@router.post(
    "/contacts/screen-icp",
    response_model=ScreenIcpResult,
    summary="Batch-screen every contact against an ICP prompt; mark matches (custom_fields.icp_qualified)",
    description=(
        "Efficient bulk filter: sends contacts to Claude in BATCHES (one call per ~60), "
        "not one call per contact, so a 1000-contact list screens in seconds. Each match "
        "is marked custom_fields.icp_qualified=true via a contact.created event the "
        "projector merges, so the list can be filtered on it. Re-running re-marks the "
        "current matches. Needs an anthropic connection."
    ),
)
async def screen_contacts_icp(
    body: ScreenIcpRequest, ctx: AuthContext = Depends(get_current_workspace)
) -> ScreenIcpResult:
    import asyncio

    from app.services.ai_jobs import _anthropic_text, _extract_json, anthropic_key

    key = await anthropic_key(ctx.workspace_id)
    if not key:
        raise HTTPException(status_code=400, detail="no anthropic connection in this workspace")
    contacts = await fetch_all(
        "SELECT id, first_name, last_name, company, headline FROM omni_contacts ORDER BY created_at"
    )
    system = (
        "You screen B2B contacts against an Ideal Customer Profile (ICP). You receive a NUMBERED "
        "list of contacts (Name | Headline | Company). Respond with ONLY a JSON object "
        '{"qualified": [<the numbers that MATCH the ICP>]} and nothing else.\n\nICP:\n' + body.prompt
    )
    sem = asyncio.Semaphore(body.concurrency)

    async def _run(batch: list[dict[str, Any]]) -> list[Any]:
        lines = []
        for i, r in enumerate(batch, 1):
            name = ((r["first_name"] or "") + " " + (r["last_name"] or "")).strip() or "(no name)"
            lines.append(f"{i}. {name} | {(r['headline'] or '')[:90]} | {r['company'] or ''}")
        async with sem:
            try:
                text, _usage = await _anthropic_text(
                    key, system, "Contacts:\n" + "\n".join(lines), 1200
                )
            except Exception:  # noqa: BLE001 — one bad batch must not fail the whole pass
                return []
        obj = _extract_json(text) or {}
        out = []
        for n in obj.get("qualified") or []:
            try:
                idx = int(n)
            except (TypeError, ValueError):
                continue
            if 1 <= idx <= len(batch):
                out.append(batch[idx - 1]["id"])
        return out

    batches = [contacts[i : i + body.batch_size] for i in range(0, len(contacts), body.batch_size)]
    results = await asyncio.gather(*[_run(b) for b in batches])
    matches = {str(cid) for group in results for cid in group}

    # Idempotent: reflect ONLY this screen. Mark matches true; unmark any contact
    # that was previously true but no longer matches (both via projector-merged
    # events, so only changed rows are touched).
    previously = await fetch_all("SELECT id FROM omni_contacts WHERE custom_fields->>'icp_qualified' = 'true'")
    stale = {str(r["id"]) for r in previously} - matches
    for cid, value in [(c, True) for c in matches] + [(c, False) for c in stale]:
        await publish_event(
            workspace_id=ctx.workspace_id,
            event_type="contact.created",
            entity_type="contact",
            entity_id=cid,
            payload={"custom_fields": {"icp_qualified": value}},
            actor_user_id=ctx.user_id,
        )
    return ScreenIcpResult(screened=len(contacts), qualified=len(matches))


class ContactCreate(BaseModel):
    email: str | None = None
    linkedin_url: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    company: str | None = None
    headline: str | None = None
    phone: str | None = None
    source: str = "manual"


@router.post(
    "/contacts",
    response_model=ContactOut,
    status_code=201,
    summary="Manually add a contact to the CRM",
    description=(
        "Create (or upsert) a single contact by hand — the recipient an "
        "outbound-first campaign reaches, or any person you want in the CRM. "
        "The id is DETERMINISTIC (UUIDv5 of workspace + linkedin/email, the same "
        "key crm.create_contact uses) so manually adding someone a source later "
        "discovers converges on ONE row instead of duplicating. Requires an email "
        "or a linkedin_url."
    ),
)
async def create_contact(
    body: ContactCreate, ctx: AuthContext = Depends(get_current_workspace)
) -> ContactOut:
    # Reuse the canonical deterministic-id + emit path so manual + discovered
    # contacts share identity (DEDUP-001) and the projector owns the write.
    from app.nodes.crm.create_contact import _contact_id
    from app.services import bus

    if not body.email and not body.linkedin_url:
        raise HTTPException(status_code=422, detail="a contact needs an email or a linkedin_url")

    contact_id = _contact_id(str(ctx.workspace_id), body.linkedin_url, body.email)
    await bus.publish_event(
        workspace_id=str(ctx.workspace_id),
        event_type="contact.created",
        entity_type="contact",
        entity_id=contact_id,
        payload={
            "email": body.email,
            "linkedin_url": body.linkedin_url,
            "first_name": body.first_name,
            "last_name": body.last_name,
            "company": body.company,
            "headline": body.headline,
            "phone": body.phone,
            "source": body.source,
        },
        actor_user_id=ctx.user_id,
    )
    # The projector writes asynchronously; upsert here too so the API returns the
    # row immediately (idempotent — same ON CONFLICT(id) shape as the projector).
    async with system_scope():
        row = await fetch_one(
            """
            INSERT INTO omni_contacts (id, workspace_id, email, first_name, last_name,
                                  company, headline, linkedin_url, phone, source)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
            ON CONFLICT (id) DO UPDATE SET
              email        = COALESCE(EXCLUDED.email,        omni_contacts.email),
              first_name   = COALESCE(EXCLUDED.first_name,   omni_contacts.first_name),
              last_name    = COALESCE(EXCLUDED.last_name,    omni_contacts.last_name),
              company      = COALESCE(EXCLUDED.company,      omni_contacts.company),
              headline     = COALESCE(EXCLUDED.headline,     omni_contacts.headline),
              linkedin_url = COALESCE(EXCLUDED.linkedin_url, omni_contacts.linkedin_url),
              phone        = COALESCE(EXCLUDED.phone,        omni_contacts.phone),
              source       = COALESCE(EXCLUDED.source,       omni_contacts.source),
              updated_at   = NOW()
            RETURNING *
            """,
            contact_id, str(ctx.workspace_id), body.email, body.first_name, body.last_name,
            body.company, body.headline, body.linkedin_url, body.phone, body.source,
        )
    return ContactOut.model_validate(row)


@router.delete("/contacts/{contact_id}", status_code=204, summary="Delete a contact")
async def delete_contact(
    contact_id: uuid.UUID, ctx: AuthContext = Depends(get_current_workspace)
) -> None:
    await _delete_entity(ctx, table="omni_contacts", entity_type="contact", entity_id=contact_id)


@router.get("/companies", response_model=list[CompanyOut], summary="List companies, with filters")
async def list_companies(
    _: AuthContext = Depends(get_current_workspace),
    q: str | None = Query(None, description="Search across name, domain, industry"),
    industry: str | None = Query(None, description="Filter by industry"),
    has_domain: bool | None = Query(None, description="True = only companies with a resolved domain"),
    limit: int = Query(100, ge=1, le=500),
) -> list[CompanyOut]:
    clauses: list[str] = []
    args: list[Any] = []
    if q and q.strip():
        args.append(f"%{q.strip()}%")
        i = len(args)
        clauses.append(f"(name ILIKE ${i} OR domain ILIKE ${i} OR industry ILIKE ${i})")
    if industry:
        args.append(industry)
        clauses.append(f"industry = ${len(args)}")
    if has_domain is True:
        clauses.append("domain IS NOT NULL AND domain <> ''")
    elif has_domain is False:
        clauses.append("(domain IS NULL OR domain = '')")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    args.append(limit)
    rows = await fetch_all(
        f"SELECT * FROM omni_companies {where} ORDER BY updated_at DESC LIMIT ${len(args)}", *args
    )
    return [CompanyOut.model_validate(r) for r in rows]


@router.delete("/companies/{company_id}", status_code=204, summary="Delete a company")
async def delete_company(
    company_id: uuid.UUID, ctx: AuthContext = Depends(get_current_workspace)
) -> None:
    await _delete_entity(ctx, table="omni_companies", entity_type="company", entity_id=company_id)


class TaskOut(BaseModel):
    id: uuid.UUID
    contact_id: uuid.UUID | None
    title: str
    due_date: datetime | None
    priority: str
    status: str
    created_at: datetime


@router.get("/tasks", response_model=list[TaskOut], summary="List tasks (worklist)")
async def list_tasks(
    _: AuthContext = Depends(get_current_workspace),
    status: str | None = Query(None, description="open | done"),
    limit: int = Query(200, ge=1, le=1000),
) -> list[TaskOut]:
    if status:
        rows = await fetch_all(
            "SELECT id, contact_id, title, due_date, priority, status, created_at "
            "FROM omni_tasks WHERE status = $1 ORDER BY (due_date IS NULL), due_date, created_at DESC LIMIT $2",
            status,
            limit,
        )
    else:
        rows = await fetch_all(
            "SELECT id, contact_id, title, due_date, priority, status, created_at "
            "FROM omni_tasks ORDER BY (status = 'done'), (due_date IS NULL), due_date, created_at DESC LIMIT $1",
            limit,
        )
    return [TaskOut.model_validate(r) for r in rows]


@router.post("/tasks/{task_id}/complete", status_code=202, summary="Mark a task done")
async def complete_task(
    task_id: uuid.UUID, ctx: AuthContext = Depends(get_current_workspace), done: bool = Query(True)
) -> dict[str, str]:
    """Flip a task open↔done. Mutation = event: publishes task.completed/.reopened
    which the projector applies to omni_tasks."""
    row = await fetch_one("SELECT id FROM omni_tasks WHERE id = $1", task_id)
    if not row:
        raise HTTPException(status_code=404, detail="task not found")
    await publish_event(
        workspace_id=ctx.workspace_id,
        event_type="task.completed" if done else "task.reopened",
        entity_type="task",
        entity_id=str(task_id),
        payload={"by": ctx.user_id},
        actor_user_id=ctx.user_id,
    )
    return {"status": "done" if done else "open"}


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


_SOURCE_BATCH_SQL = """
(
    l.contact_id IS NULL
    AND jsonb_typeof(l.custom_fields->'companies') = 'array'
    AND COALESCE(l.custom_fields->'item'->>'linkedin_url', '') = ''
    AND COALESCE(l.custom_fields->'item'->>'company_name', '') = ''
    AND COALESCE(l.custom_fields->'verification', 'null'::jsonb) = 'null'::jsonb
    AND COALESCE(l.custom_fields->'company_resolution', 'null'::jsonb) = 'null'::jsonb
)
"""


def _lead_filters(
    workflow_id: uuid.UUID | None,
    include_source_batches: bool,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    args: list[Any] = []
    if workflow_id:
        args.append(workflow_id)
        clauses.append(f"l.workflow_id = ${len(args)}")
    if not include_source_batches:
        clauses.append(f"NOT {_SOURCE_BATCH_SQL}")
    return (f"WHERE {' AND '.join(clauses)}" if clauses else ""), args


@router.get("/leads", response_model=list[LeadOut], summary="List prospect leads with contact identity and display fields")
async def list_leads(
    _: AuthContext = Depends(get_current_workspace),
    workflow_id: uuid.UUID | None = Query(None),
    include_source_batches: bool = Query(
        False,
        description="Include operational source-run roots. Off by default because they are runs, not prospects.",
    ),
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
               l.fanout_total, l.fanout_done, l.origin_node_id,
               n.node_type AS current_node_type,
               o.node_type AS origin_node_type,
               c.first_name AS c_first_name, c.last_name AS c_last_name,
               c.email AS c_email, c.company AS c_company, c.headline AS c_headline,
               c.linkedin_url AS c_linkedin_url, c.phone AS c_phone
        FROM omni_leads l
        LEFT JOIN omni_contacts c ON c.id = l.contact_id AND c.workspace_id = l.workspace_id
        LEFT JOIN omni_workflow_nodes n ON n.id = l.current_node_id
        LEFT JOIN omni_workflow_nodes o ON o.id = l.origin_node_id
    """
    where, args = _lead_filters(workflow_id, include_source_batches)
    args.append(limit)
    rows = await fetch_all(
        select + f" {where} ORDER BY l.updated_at DESC LIMIT ${len(args)}",
        *args,
    )

    columns = lead_columns.derive_columns(await _workflow_node_types(workflow_id))
    return [_lead_out(dict(r), columns) for r in rows]


@router.get(
    "/leads/summary",
    response_model=LeadSummary,
    summary="Exact prospect-lead counts for the selected campaign",
)
async def lead_summary(
    _: AuthContext = Depends(get_current_workspace),
    workflow_id: uuid.UUID | None = Query(None),
    include_source_batches: bool = Query(False),
) -> LeadSummary:
    where, args = _lead_filters(workflow_id, include_source_batches)
    row = await fetch_one(
        f"""
        SELECT
            COUNT(DISTINCT l.id) AS total,
            COUNT(DISTINCT l.id) FILTER (WHERE l.status = 'active') AS active,
            COUNT(DISTINCT l.id) FILTER (
                WHERE l.contact_id IS NOT NULL
                   OR COALESCE(l.custom_fields->'item'->>'linkedin_url', '') <> ''
            ) AS people,
            COUNT(DISTINCT l.id) FILTER (
                WHERE l.contact_id IS NULL
                  AND (
                    COALESCE(l.custom_fields->'item'->>'company_name', '') <> ''
                    OR COALESCE(l.custom_fields->'company_resolution', 'null'::jsonb) <> 'null'::jsonb
                  )
            ) AS companies,
            COUNT(DISTINCT s.lead_id) FILTER (WHERE s.tier = 'hot') AS hot
        FROM omni_leads l
        LEFT JOIN omni_lead_scores s ON s.lead_id = l.id
        {where}
        """,
        *args,
    )
    return LeadSummary(**{k: int((row or {}).get(k) or 0) for k in LeadSummary.model_fields})


@router.delete("/leads/{lead_id}", status_code=204, summary="Delete a lead")
async def delete_lead(
    lead_id: uuid.UUID, ctx: AuthContext = Depends(get_current_workspace)
) -> None:
    await _delete_entity(ctx, table="omni_leads", entity_type="lead", entity_id=lead_id)


# ── Lead journey (per-lead reconstruction of the distributed run) ─────────────
# A lead's story is normally scattered across dispatcher/muscle/Flink/transitions
# /projector. app/tools/trace.py stitches it back from correlation_id; this is
# the same reconstruction exposed as an HTTP read, but lead-scoped: a lead does
# not carry its correlation_id directly, so we find it via the lead's archived
# events (entity_id = lead_id), then assemble timeline + lineage + AI cost.
class JourneyEvent(BaseModel):
    occurred_at: datetime
    event_type: str
    node_id: uuid.UUID | None
    node_label: str | None  # human node_type, e.g. "verify_person", not a UUID


class LineageLead(BaseModel):
    id: uuid.UUID
    identity: str
    status: str
    stage: str


class JourneyCost(BaseModel):
    total_usd: float
    by_kind: dict[str, float]
    calls: int


class SendOutcomeOut(BaseModel):
    """One outbound send attempt — the durable, queryable record (OBSERVABILITY-001).
    This is what makes 'why did this send fail?' a query instead of a log hunt."""
    occurred_at: datetime
    channel: str
    mode: str | None
    status: str
    error_code: str | None
    error_detail: str | None
    provider_ids: dict[str, Any]
    retriable: bool


class LeadJourneyOut(BaseModel):
    lead: LeadOut
    parent: LineageLead | None
    children: list[LineageLead]
    timeline: list[JourneyEvent]
    cost: JourneyCost
    sends: list[SendOutcomeOut]
    status_reason: str


def _lineage_lead(row: dict[str, Any]) -> LineageLead:
    cf = row.get("custom_fields") or {}
    if isinstance(cf, str):
        cf = json.loads(cf)
    identity = lead_columns.lead_identity(cf, None, str(row["id"]))
    stage = lead_columns.lead_stage(cf, has_contact=row.get("contact_id") is not None)
    return LineageLead(id=row["id"], identity=identity, status=row["status"], stage=stage)


# Human, status-specific explanation of where a lead is and why. Pure derivation
# over the lead row + its fan-out node type + last event — so the drawer answers
# "why is this stuck?" instead of just showing a status word.
def _status_reason(lead: dict[str, Any], origin_type: str | None, last_event: str | None) -> str:
    status = lead.get("status") or "active"
    if status == "waiting":
        total = lead.get("fanout_total") or 0
        done = lead.get("fanout_done") or 0
        if total and total > 0:
            kind = "branches" if origin_type == "flow.race" else "child leads"
            return f"Waiting for {done}/{total} {kind} to finish."
        current_node_type = lead.get("current_node_type")
        if current_node_type in ("flow.delay", "flow.wait_until"):
            return "Waiting for a delay/schedule window."
        return "Parked (waiting on limits)."
    if status == "errored":
        return "A node failed and no on-error path was wired; the lead stopped here."
    if status == "suppressed":
        return "Recipient is on the suppression list (unsubscribe / do-not-contact) — no message was sent."
    if status == "converted":
        return "Reached a goal node — counted as a conversion."
    if status == "ended":
        return "Reached the end of its sequence (or the campaign's end date passed)."
    if status == "cancelled":
        return "Cancelled — a sibling branch won a race, or the run was stopped."
    if status == "completed":
        return "Finished its sequence with nothing left to do."
    # active
    if last_event:
        return f"In flight — last action: {last_event}."
    return "In flight."


@router.get(
    "/leads/{lead_id}/journey",
    response_model=LeadJourneyOut,
    summary="Reconstruct one lead's full journey: timeline, lineage, cost, why-stuck",
)
async def lead_journey(
    lead_id: uuid.UUID, ctx: AuthContext = Depends(get_current_workspace)
) -> LeadJourneyOut:
    # TENANT-LEAK-001: this route is authenticated and tenant-scoped, so it must
    # run under the REQUEST tenant (RLS filters cross-tenant rows) — NOT
    # system_scope(), which sets the all-zero system workspace and BYPASSES RLS.
    # The old code wrapped every query in system_scope() with no workspace_id
    # filter, so any logged-in user could read ANY workspace's lead (PII, cost,
    # lineage) by guessing a lead UUID. Every query below now also carries an
    # explicit workspace_id guard as defence-in-depth behind RLS.
    ws = ctx.workspace_id
    lead = await fetch_one(
        """
        SELECT l.id, l.contact_id, l.workflow_id, l.current_node_id, l.status,
               l.custom_fields, l.created_at, l.updated_at,
               l.parent_lead_id, l.origin_node_id, l.fanout_total, l.fanout_done,
               c.first_name AS c_first_name, c.last_name AS c_last_name,
               c.email AS c_email, c.company AS c_company, c.headline AS c_headline,
               c.linkedin_url AS c_linkedin_url, c.phone AS c_phone
        FROM omni_leads l
        LEFT JOIN omni_contacts c ON c.id = l.contact_id AND c.workspace_id = l.workspace_id
        WHERE l.id = $1 AND l.workspace_id = $2
        """,
        lead_id,
        ws,
    )
    if not lead:
        raise HTTPException(status_code=404, detail="lead not found")
    lead = dict(lead)

    # Timeline: every archived event whose entity is this lead, oldest first,
    # with the node UUID resolved to its human node_type. (idx on entity.)
    events = await fetch_all(
        """
        SELECT a.occurred_at, a.event_type, a.payload, a.correlation_id,
               n.node_type AS node_label
        FROM omni_events_archive a
        LEFT JOIN omni_workflow_nodes n
               ON n.id = NULLIF(a.payload->>'node_id', '')::uuid
        WHERE a.entity_type = 'lead' AND a.entity_id = $1 AND a.workspace_id = $2
        ORDER BY a.occurred_at ASC, a.kafka_offset ASC
        """,
        lead_id,
        ws,
    )
    # Lineage — parent (if a fan-out child) + direct children (fan-out).
    parent_row = None
    if lead.get("parent_lead_id"):
        parent_row = await fetch_one(
            "SELECT id, status, contact_id, custom_fields FROM omni_leads WHERE id = $1 AND workspace_id = $2",
            lead["parent_lead_id"],
            ws,
        )
    children = await fetch_all(
        "SELECT id, status, contact_id, custom_fields FROM omni_leads "
        "WHERE parent_lead_id = $1 AND workspace_id = $2 ORDER BY created_at ASC LIMIT 200",
        lead_id,
        ws,
    )
    # The fan-out node's type (drives the waiting status_reason wording).
    origin_type = None
    if lead.get("origin_node_id"):
        origin = await fetch_one(
            "SELECT node_type FROM omni_workflow_nodes WHERE id = $1 AND workspace_id = $2",
            lead["origin_node_id"],
            ws,
        )
        origin_type = (origin or {}).get("node_type")

    # Cost: AI jobs for every correlation_id this lead's events touched.
    cids = {str(e["correlation_id"]) for e in events if e.get("correlation_id")}
    by_kind: dict[str, float] = {}
    calls = 0
    if cids:
        jobs = await fetch_all(
            "SELECT kind, cost_usd FROM omni_ai_jobs WHERE correlation_id = ANY($1::uuid[]) AND workspace_id = $2",
            list(cids),
            ws,
        )
        for j in jobs:
            calls += 1
            by_kind[j["kind"]] = round(by_kind.get(j["kind"], 0.0) + float(j.get("cost_usd") or 0), 6)
    cost = JourneyCost(total_usd=round(sum(by_kind.values()), 6), by_kind=by_kind, calls=calls)

    # OBSERVABILITY-001: every outbound send attempt for this lead, newest first —
    # status + the failure reason + provider handles. RLS-scoped + ws-filtered.
    send_rows = await fetch_all(
        """
        SELECT occurred_at, channel, mode, status, error_code, error_detail,
               provider_ids, retriable
        FROM omni_send_outcomes
        WHERE workspace_id = $1 AND lead_id = $2
        ORDER BY occurred_at DESC
        LIMIT 100
        """,
        ws,
        lead_id,
    )
    sends = [
        SendOutcomeOut(
            occurred_at=s["occurred_at"],
            channel=s["channel"],
            mode=s.get("mode"),
            status=s["status"],
            error_code=s.get("error_code"),
            error_detail=s.get("error_detail"),
            provider_ids=s.get("provider_ids") or {},
            retriable=bool(s.get("retriable")),
        )
        for s in send_rows
    ]

    timeline = [
        JourneyEvent(
            occurred_at=e["occurred_at"],
            event_type=e["event_type"],
            node_id=(e["payload"] or {}).get("node_id"),
            node_label=e.get("node_label"),
        )
        for e in events
    ]
    last_event = timeline[-1].event_type if timeline else None

    columns = lead_columns.derive_columns(await _workflow_node_types(lead.get("workflow_id")))
    return LeadJourneyOut(
        lead=_lead_out(lead, columns),
        parent=_lineage_lead(dict(parent_row)) if parent_row else None,
        children=[_lineage_lead(dict(c)) for c in children],
        timeline=timeline,
        cost=cost,
        sends=sends,
        status_reason=_status_reason(lead, origin_type, last_event),
    )


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
        status_reason=_status_reason(row, row.get("origin_node_type"), None),
    )


# ── T2: lead-gen efficiency + cost analytics ─────────────────────────────────
# omni_pipeline_metrics is written per-run by the projector but was never
# exposed. This aggregates it for the workspace so the Analytics page can show
# real funnel volumes and AI/Serper cost. RLS binds the tenant.
class AnalyticsSummary(BaseModel):
    runs: int
    companies_collected: int
    companies_qualified: int
    companies_rejected: int
    people_found: int
    people_verified: int
    leads_created: int
    serper_calls: int
    claude_calls: int
    claude_input_tokens: int
    claude_output_tokens: int
    total_cost: float
    email_opens: int
    email_clicks: int
    last_run_at: datetime | None


@router.get("/analytics", response_model=AnalyticsSummary, summary="Lead-gen efficiency + cost rollup")
async def analytics_summary(_: AuthContext = Depends(get_current_workspace)) -> AnalyticsSummary:
    row = await fetch_all(
        """
        SELECT
            COUNT(*)                              AS runs,
            COALESCE(SUM(companies_collected), 0) AS companies_collected,
            COALESCE(SUM(companies_qualified), 0) AS companies_qualified,
            COALESCE(SUM(companies_rejected), 0)  AS companies_rejected,
            COALESCE(SUM(people_found), 0)        AS people_found,
            COALESCE(SUM(people_verified), 0)     AS people_verified,
            COALESCE(SUM(leads_created), 0)       AS leads_created,
            COALESCE(SUM(serper_calls), 0)        AS serper_calls,
            COALESCE(SUM(claude_calls), 0)        AS claude_calls,
            COALESCE(SUM(claude_input_tokens), 0) AS claude_input_tokens,
            COALESCE(SUM(claude_output_tokens), 0) AS claude_output_tokens,
            COALESCE(SUM(total_cost), 0)          AS total_cost,
            MAX(started_at)                       AS last_run_at
        FROM omni_pipeline_metrics
        """
    )
    r = dict(row[0]) if row else {}
    # T3: email engagement rollup — opens/clicks across the workspace.
    eng = await fetch_all(
        """
        SELECT
            COALESCE(SUM((event_type = 'open')::int), 0)  AS email_opens,
            COALESCE(SUM((event_type = 'click')::int), 0) AS email_clicks
        FROM omni_email_tracking
        """
    )
    e = dict(eng[0]) if eng else {}
    return AnalyticsSummary(
        runs=int(r.get("runs") or 0),
        companies_collected=int(r.get("companies_collected") or 0),
        companies_qualified=int(r.get("companies_qualified") or 0),
        companies_rejected=int(r.get("companies_rejected") or 0),
        people_found=int(r.get("people_found") or 0),
        people_verified=int(r.get("people_verified") or 0),
        leads_created=int(r.get("leads_created") or 0),
        serper_calls=int(r.get("serper_calls") or 0),
        claude_calls=int(r.get("claude_calls") or 0),
        claude_input_tokens=int(r.get("claude_input_tokens") or 0),
        claude_output_tokens=int(r.get("claude_output_tokens") or 0),
        total_cost=float(r.get("total_cost") or 0),
        email_opens=int(e.get("email_opens") or 0),
        email_clicks=int(e.get("email_clicks") or 0),
        last_run_at=r.get("last_run_at"),
    )
