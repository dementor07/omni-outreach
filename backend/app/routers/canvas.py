"""Canvas (workflow DAG) CRUD.

  GET    /canvas/workflows
  POST   /canvas/workflows
  GET    /canvas/workflows/{id}                 returns workflow + nodes + edges
  PATCH  /canvas/workflows/{id}
  DELETE /canvas/workflows/{id}                 soft-delete (status='archived')

  POST   /canvas/workflows/{id}/nodes
  PATCH  /canvas/workflows/{id}/nodes/{node_id}
  DELETE /canvas/workflows/{id}/nodes/{node_id}

  POST   /canvas/workflows/{id}/edges
  DELETE /canvas/workflows/{id}/edges/{edge_id}

Replaces the legacy ``campaigns`` + ``sequence_nodes`` + ``sequence_edges``
routers with one shape.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import acquire, execute, fetch_all, fetch_one
from app.routers.integrations import SendingAccountOut

log = logging.getLogger(__name__)

router = APIRouter()


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field("UTC", max_length=64)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    status: Literal["draft", "active", "paused", "archived"] | None = None
    timezone: str | None = Field(None, max_length=64)
    # B6 campaign schedule window. Outbound sends hold until start_at and stop
    # after end_at; both null = always-on.
    start_at: datetime | None = None
    end_at: datetime | None = None
    daily_cap: int | None = Field(None, ge=0)
    earliest_hour: int | None = Field(None, ge=0, le=23)
    latest_hour: int | None = Field(None, ge=1, le=24)
    days_of_week: list[int] | None = None


class NodeCreate(BaseModel):
    node_type: str = Field(min_length=1, max_length=120)
    position_x: float = 0
    position_y: float = 0
    config: dict[str, Any] = Field(default_factory=dict)


class NodeUpdate(BaseModel):
    position_x: float | None = None
    position_y: float | None = None
    config: dict[str, Any] | None = None


class EdgeCreate(BaseModel):
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    source_handle: str = "default"
    target_handle: str = "default"


class GraphNodeIn(BaseModel):
    id: uuid.UUID
    node_type: str = Field(min_length=1, max_length=120)
    position_x: float = 0
    position_y: float = 0
    config: dict[str, Any] = Field(default_factory=dict)


class GraphEdgeIn(BaseModel):
    id: uuid.UUID | None = None
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    source_handle: str = "default"
    target_handle: str = "default"


class GraphSave(BaseModel):
    nodes: list[GraphNodeIn] = Field(default_factory=list)
    edges: list[GraphEdgeIn] = Field(default_factory=list)


class WorkflowOut(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    timezone: str
    start_at: datetime | None = None
    end_at: datetime | None = None
    daily_cap: int | None = None
    earliest_hour: int | None = None
    latest_hour: int | None = None
    days_of_week: list[int] | None = None
    created_at: datetime
    updated_at: datetime


class NodeOut(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    node_type: str
    position_x: float
    position_y: float
    config: dict[str, Any]


class EdgeOut(BaseModel):
    id: uuid.UUID
    workflow_id: uuid.UUID
    source_node_id: uuid.UUID
    target_node_id: uuid.UUID
    source_handle: str
    target_handle: str


class WorkflowDetail(BaseModel):
    workflow: WorkflowOut
    nodes: list[NodeOut]
    edges: list[EdgeOut]


# ── Workflows ────────────────────────────────────────────────────────────────


@router.get("/workflows", response_model=list[WorkflowOut], summary="List workflows in this workspace")
async def list_workflows(_: AuthContext = Depends(get_current_workspace)) -> list[WorkflowOut]:
    rows = await fetch_all("SELECT * FROM omni_workflows ORDER BY updated_at DESC")
    return [WorkflowOut.model_validate(r) for r in rows]


@router.post("/workflows", response_model=WorkflowOut, status_code=201, summary="Create a new workflow")
async def create_workflow(body: WorkflowCreate, ctx: AuthContext = Depends(get_current_workspace)) -> WorkflowOut:
    row = await fetch_one(
        "INSERT INTO omni_workflows (workspace_id, name, timezone) VALUES ($1, $2, $3) RETURNING *",
        ctx.workspace_id,
        body.name,
        body.timezone,
    )
    return WorkflowOut.model_validate(row)


class TemplateInstantiate(BaseModel):
    template_id: str = Field(min_length=1, max_length=120)
    name: str | None = Field(None, min_length=1, max_length=200)
    timezone: str = Field("UTC", max_length=64)


@router.get("/templates", summary="List starter campaign templates")
async def list_campaign_templates(_: AuthContext = Depends(get_current_workspace)) -> list[dict[str, str]]:
    from app.canvas_templates import list_templates

    return list_templates()


@router.post(
    "/workflows/from-template",
    response_model=WorkflowDetail,
    status_code=201,
    summary="Create a workflow pre-seeded from a starter template (cold-start fix)",
)
async def create_from_template(
    body: TemplateInstantiate, ctx: AuthContext = Depends(get_current_workspace)
) -> WorkflowDetail:
    from app.canvas_templates import TEMPLATES

    tpl = TEMPLATES.get(body.template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail=f"unknown template {body.template_id!r}")

    # Assign fresh UUIDs, mapping each template node key -> real id so edges
    # resolve. One transaction: workflow + nodes + edges (mirrors save_graph).
    key_to_id = {n.key: uuid.uuid4() for n in tpl.nodes}
    async with acquire() as conn:
        async with conn.transaction():
            wf = await conn.fetchrow(
                "INSERT INTO omni_workflows (workspace_id, name, timezone) VALUES ($1, $2, $3) RETURNING *",
                ctx.workspace_id, body.name or tpl.name, body.timezone,
            )
            wf_id = wf["id"]
            for n in tpl.nodes:
                await conn.execute(
                    """
                    INSERT INTO omni_workflow_nodes
                      (id, workspace_id, workflow_id, node_type, position_x, position_y, config)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    key_to_id[n.key], ctx.workspace_id, wf_id, n.node_type,
                    n.position_x, n.position_y, json.dumps(n.config),
                )
            for e in tpl.edges:
                src, tgt = key_to_id.get(e.source), key_to_id.get(e.target)
                if not src or not tgt:
                    continue
                await conn.execute(
                    """
                    INSERT INTO omni_workflow_edges
                      (id, workspace_id, workflow_id, source_node_id, target_node_id, source_handle, target_handle)
                    VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6)
                    """,
                    ctx.workspace_id, wf_id, src, tgt, e.source_handle, e.target_handle,
                )
            nodes = await conn.fetch("SELECT * FROM omni_workflow_nodes WHERE workflow_id = $1", wf_id)
            edges = await conn.fetch("SELECT * FROM omni_workflow_edges WHERE workflow_id = $1", wf_id)

    return WorkflowDetail(
        workflow=WorkflowOut.model_validate(dict(wf)),
        nodes=[NodeOut.model_validate(dict(n)) for n in nodes],
        edges=[EdgeOut.model_validate(dict(e)) for e in edges],
    )


@router.get("/workflows/{workflow_id}", response_model=WorkflowDetail, summary="Fetch a workflow with all its nodes and edges")
async def get_workflow(workflow_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)) -> WorkflowDetail:
    wf = await fetch_one("SELECT * FROM omni_workflows WHERE id = $1", workflow_id)
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")
    nodes = await fetch_all("SELECT * FROM omni_workflow_nodes WHERE workflow_id = $1", workflow_id)
    edges = await fetch_all("SELECT * FROM omni_workflow_edges WHERE workflow_id = $1", workflow_id)
    return WorkflowDetail(
        workflow=WorkflowOut.model_validate(wf),
        nodes=[NodeOut.model_validate(n) for n in nodes],
        edges=[EdgeOut.model_validate(e) for e in edges],
    )


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut, summary="Update a workflow's name, status, timezone, or schedule window")
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    _: AuthContext = Depends(get_current_workspace),
) -> WorkflowOut:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")

    if "days_of_week" in fields:
        fields["days_of_week"] = json.dumps(fields["days_of_week"])

    set_clauses = []
    for i, k in enumerate(fields):
        if k == "days_of_week":
            set_clauses.append(f"{k} = ${i + 2}::jsonb")
        else:
            set_clauses.append(f"{k} = ${i + 2}")

    set_sql = ", ".join(set_clauses)
    row = await fetch_one(
        f"UPDATE omni_workflows SET {set_sql}, updated_at = NOW() WHERE id = $1 RETURNING *",
        workflow_id,
        *fields.values(),
    )
    if not row:
        raise HTTPException(status_code=404, detail="workflow not found")
    return WorkflowOut.model_validate(row)


@router.delete("/workflows/{workflow_id}", status_code=204, summary="Archive a workflow")
async def archive_workflow(workflow_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)) -> None:
    await execute("UPDATE omni_workflows SET status = 'archived', updated_at = NOW() WHERE id = $1", workflow_id)


class PoolUpdate(BaseModel):
    sending_account_ids: list[uuid.UUID]


@router.get("/workflows/{id}/accounts", response_model=list[SendingAccountOut], summary="Fetch pooled accounts for a campaign")
async def get_workflow_pool(id: uuid.UUID, ctx: AuthContext = Depends(get_current_workspace)) -> list[SendingAccountOut]:
    rows = await fetch_all(
        """
        SELECT a.*
        FROM omni_sending_accounts a
        JOIN omni_campaign_sending_accounts p ON a.id = p.sending_account_id
        WHERE p.workflow_id = $1 AND p.workspace_id = $2
        """,
        id, ctx.workspace_id
    )
    return [SendingAccountOut.model_validate(r) for r in rows]


@router.put("/workflows/{id}/accounts", response_model=list[SendingAccountOut], summary="Replace pooled accounts for a campaign")
async def update_workflow_pool(id: uuid.UUID, body: PoolUpdate, ctx: AuthContext = Depends(get_current_workspace)) -> list[SendingAccountOut]:
    async with acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM omni_campaign_sending_accounts WHERE workflow_id = $1 AND workspace_id = $2", id, ctx.workspace_id)
            for account_id in body.sending_account_ids:
                acc = await conn.fetchrow("SELECT id FROM omni_sending_accounts WHERE id = $1", account_id)
                if not acc:
                    raise HTTPException(status_code=400, detail=f"invalid sending account id: {account_id}")

                await conn.execute(
                    "INSERT INTO omni_campaign_sending_accounts (workspace_id, workflow_id, sending_account_id) VALUES ($1, $2, $3)",
                    ctx.workspace_id, id, account_id
                )

            rows = await conn.fetch(
                """
                SELECT a.*
                FROM omni_sending_accounts a
                JOIN omni_campaign_sending_accounts p ON a.id = p.sending_account_id
                WHERE p.workflow_id = $1 AND p.workspace_id = $2
                """,
                id, ctx.workspace_id
            )
    return [SendingAccountOut.model_validate(r) for r in rows]


# ── Nodes ────────────────────────────────────────────────────────────────────


@router.post("/workflows/{workflow_id}/nodes", response_model=NodeOut, status_code=201, summary="Add a node to a workflow")
async def add_node(
    workflow_id: uuid.UUID,
    body: NodeCreate,
    ctx: AuthContext = Depends(get_current_workspace),
) -> NodeOut:
    row = await fetch_one(
        """
        INSERT INTO omni_workflow_nodes (workspace_id, workflow_id, node_type, position_x, position_y, config)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb) RETURNING *
        """,
        ctx.workspace_id,
        workflow_id,
        body.node_type,
        body.position_x,
        body.position_y,
        body.config,
    )
    return NodeOut.model_validate(row)


@router.patch("/workflows/{workflow_id}/nodes/{node_id}", response_model=NodeOut, summary="Update a node's position or config")
async def update_node(
    workflow_id: uuid.UUID,
    node_id: uuid.UUID,
    body: NodeUpdate,
    _: AuthContext = Depends(get_current_workspace),
) -> NodeOut:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    set_sql = ", ".join(f"{k} = ${i + 3}" for i, k in enumerate(fields))
    row = await fetch_one(
        f"UPDATE omni_workflow_nodes SET {set_sql} WHERE id = $1 AND workflow_id = $2 RETURNING *",
        node_id,
        workflow_id,
        *fields.values(),
    )
    if not row:
        raise HTTPException(status_code=404, detail="node not found")
    return NodeOut.model_validate(row)


@router.delete("/workflows/{workflow_id}/nodes/{node_id}", status_code=204, summary="Remove a node (and its edges)")
async def remove_node(
    workflow_id: uuid.UUID,
    node_id: uuid.UUID,
    _: AuthContext = Depends(get_current_workspace),
) -> None:
    await execute("DELETE FROM omni_workflow_nodes WHERE id = $1 AND workflow_id = $2", node_id, workflow_id)


# ── Edges ────────────────────────────────────────────────────────────────────


@router.post("/workflows/{workflow_id}/edges", response_model=EdgeOut, status_code=201, summary="Wire two nodes together")
async def add_edge(
    workflow_id: uuid.UUID,
    body: EdgeCreate,
    ctx: AuthContext = Depends(get_current_workspace),
) -> EdgeOut:
    row = await fetch_one(
        """
        INSERT INTO omni_workflow_edges (workspace_id, workflow_id, source_node_id, target_node_id, source_handle, target_handle)
        VALUES ($1, $2, $3, $4, $5, $6) RETURNING *
        """,
        ctx.workspace_id,
        workflow_id,
        body.source_node_id,
        body.target_node_id,
        body.source_handle,
        body.target_handle,
    )
    return EdgeOut.model_validate(row)


@router.delete("/workflows/{workflow_id}/edges/{edge_id}", status_code=204, summary="Remove an edge")
async def remove_edge(
    workflow_id: uuid.UUID,
    edge_id: uuid.UUID,
    _: AuthContext = Depends(get_current_workspace),
) -> None:
    await execute("DELETE FROM omni_workflow_edges WHERE id = $1 AND workflow_id = $2", edge_id, workflow_id)


# ── Bulk graph save ────────────────────────────────────────────────────────────


@router.put(
    "/workflows/{workflow_id}/graph",
    response_model=WorkflowDetail,
    summary="Replace a workflow's entire node+edge graph in one transaction",
    description=(
        "Atomically replaces all nodes and edges for the workflow with the posted "
        "set. Client-supplied node ids are preserved so the canvas can save the "
        "whole graph in a single call (local-state-first editing). Returns the "
        "saved workflow with its nodes and edges."
    ),
)
async def save_graph(
    workflow_id: uuid.UUID,
    body: GraphSave,
    ctx: AuthContext = Depends(get_current_workspace),
) -> WorkflowDetail:
    async with acquire() as conn:
        async with conn.transaction():
            wf = await conn.fetchrow("SELECT * FROM omni_workflows WHERE id = $1", workflow_id)
            if not wf:
                raise HTTPException(status_code=404, detail="workflow not found")

            # Replace-all: wipe then re-insert. Edges first (FK-free here, but keep order tidy).
            await conn.execute("DELETE FROM omni_workflow_edges WHERE workflow_id = $1", workflow_id)
            await conn.execute("DELETE FROM omni_workflow_nodes WHERE workflow_id = $1", workflow_id)

            node_ids: set[uuid.UUID] = set()
            for n in body.nodes:
                await conn.execute(
                    """
                    INSERT INTO omni_workflow_nodes
                      (id, workspace_id, workflow_id, node_type, position_x, position_y, config)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    n.id, ctx.workspace_id, workflow_id, n.node_type, n.position_x, n.position_y, n.config,
                )
                node_ids.add(n.id)

            for e in body.edges:
                # Skip dangling edges whose endpoints aren't in the posted node set.
                if e.source_node_id not in node_ids or e.target_node_id not in node_ids:
                    continue
                await conn.execute(
                    """
                    INSERT INTO omni_workflow_edges
                      (id, workspace_id, workflow_id, source_node_id, target_node_id, source_handle, target_handle)
                    VALUES (COALESCE($1, gen_random_uuid()), $2, $3, $4, $5, $6, $7)
                    """,
                    e.id, ctx.workspace_id, workflow_id,
                    e.source_node_id, e.target_node_id, e.source_handle, e.target_handle,
                )

            await conn.execute("UPDATE omni_workflows SET updated_at = NOW() WHERE id = $1", workflow_id)

            wf_row = await conn.fetchrow("SELECT * FROM omni_workflows WHERE id = $1", workflow_id)
            nodes = await conn.fetch("SELECT * FROM omni_workflow_nodes WHERE workflow_id = $1", workflow_id)
            edges = await conn.fetch("SELECT * FROM omni_workflow_edges WHERE workflow_id = $1", workflow_id)

    return WorkflowDetail(
        workflow=WorkflowOut.model_validate(dict(wf_row)),
        nodes=[NodeOut.model_validate(dict(n)) for n in nodes],
        edges=[EdgeOut.model_validate(dict(e)) for e in edges],
    )


# ── Run (enroll a seed lead at the entry node) ─────────────────────────────────


class RunRequest(BaseModel):
    # Optionally start at a specific node (defaults to the workflow's entry node
    # — the one with no incoming edge). Useful to re-run from a particular source.
    start_node_id: uuid.UUID | None = None


class RunResponse(BaseModel):
    lead_id: uuid.UUID
    workflow_id: uuid.UUID
    start_node_id: uuid.UUID
    node_type: str
    correlation_id: uuid.UUID
    handle: str
    events_published: int


@router.post(
    "/workflows/{workflow_id}/run",
    response_model=RunResponse,
    summary="Run a workflow — enroll a seed lead at the entry node and fire it",
    description=(
        "Creates a seed lead positioned at the workflow's entry (source) node and "
        "fires that node, publishing its intent event(s) so the dispatcher routes "
        "the muscle command and the pipeline begins. This is the missing trigger: "
        "without it, workflows are inert CRUD and no lead is ever produced. The "
        "source's discovered entities fan out into child leads via flow.for_each, "
        "which then appear in the Leads view."
    ),
)
async def run_workflow(
    workflow_id: uuid.UUID,
    body: RunRequest,
    ctx: AuthContext = Depends(get_current_workspace),
) -> RunResponse:
    from app.execution import run as runner

    wf = await fetch_one(
        "SELECT id FROM omni_workflows WHERE id = $1 AND workspace_id = $2", workflow_id, ctx.workspace_id
    )
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")

    start_node = None
    if body.start_node_id:
        start_node = await fetch_one(
            "SELECT id, node_type, config FROM omni_workflow_nodes WHERE id = $1 AND workflow_id = $2 AND workspace_id = $3",
            body.start_node_id, workflow_id, ctx.workspace_id,
        )
        if not start_node:
            raise HTTPException(status_code=404, detail="start_node_id not in this workflow")

    # The single seed-and-fire path (shared with the objective re-seed).
    outcome = await runner.seed_and_run(
        workspace_id=ctx.workspace_id,
        workflow_id=str(workflow_id),
        start_node=dict(start_node) if start_node else None,
        actor_user_id=ctx.user_id,
    )
    if outcome.error and not outcome.lead_id:
        raise HTTPException(status_code=400, detail=outcome.error)
    if outcome.error:
        raise HTTPException(status_code=422, detail=f"entry node error: {outcome.error}")

    return RunResponse(
        lead_id=uuid.UUID(outcome.lead_id),
        workflow_id=workflow_id,
        start_node_id=uuid.UUID(outcome.node_id),
        node_type=outcome.node_type,
        correlation_id=uuid.UUID(outcome.correlation_id),
        handle=outcome.handle,
        events_published=outcome.events_published,
    )
