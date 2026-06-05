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

import logging
import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import app.nodes as noderegistry
from app.auth import AuthContext, get_current_workspace
from app.db import acquire, execute, fetch_all, fetch_one
from app.services import bus

log = logging.getLogger(__name__)

router = APIRouter()


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field("UTC", max_length=64)


class WorkflowUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    status: Literal["draft", "active", "paused", "archived"] | None = None
    timezone: str | None = Field(None, max_length=64)


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


@router.patch("/workflows/{workflow_id}", response_model=WorkflowOut, summary="Update a workflow's name, status, or timezone")
async def update_workflow(
    workflow_id: uuid.UUID,
    body: WorkflowUpdate,
    _: AuthContext = Depends(get_current_workspace),
) -> WorkflowOut:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    set_sql = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(fields))
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


async def _entry_node(workflow_id: uuid.UUID, workspace_id: str) -> dict | None:
    """The workflow's entry node — the one no edge targets. If several qualify
    (parallel sources), prefer a source.* node, else the first by position."""
    nodes = await fetch_all(
        "SELECT id, node_type, config FROM omni_workflow_nodes WHERE workflow_id = $1 AND workspace_id = $2 ORDER BY position_y, position_x",
        workflow_id,
        workspace_id,
    )
    if not nodes:
        return None
    targeted = await fetch_all(
        "SELECT DISTINCT target_node_id FROM omni_workflow_edges WHERE workflow_id = $1 AND workspace_id = $2",
        workflow_id,
        workspace_id,
    )
    targeted_ids = {str(r["target_node_id"]) for r in targeted}
    roots = [n for n in nodes if str(n["id"]) not in targeted_ids]
    if not roots:
        return None
    for n in roots:
        if str(n["node_type"]).startswith("source."):
            return n
    return roots[0]


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
    wf = await fetch_one(
        "SELECT * FROM omni_workflows WHERE id = $1 AND workspace_id = $2", workflow_id, ctx.workspace_id
    )
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")

    if body.start_node_id:
        node = await fetch_one(
            "SELECT id, node_type, config FROM omni_workflow_nodes WHERE id = $1 AND workflow_id = $2 AND workspace_id = $3",
            body.start_node_id,
            workflow_id,
            ctx.workspace_id,
        )
        if not node:
            raise HTTPException(status_code=404, detail="start_node_id not in this workflow")
    else:
        node = await _entry_node(workflow_id, ctx.workspace_id)
        if not node:
            raise HTTPException(status_code=400, detail="workflow has no entry node to run (add a source node)")

    node_type = str(node["node_type"])
    try:
        _manifest, execute_fn = noderegistry.get(node_type)
    except KeyError as e:
        raise HTTPException(status_code=400, detail=f"entry node type {node_type!r} is not registered") from e

    lead_id = str(uuid.uuid4())
    node_id = str(node["id"])
    correlation_id = str(uuid.uuid4())

    # Seed lead positioned at the entry node. No contact yet — a source run
    # discovers entities that fan out into child leads (each carrying its item
    # in custom_fields) which then advance toward a contact.
    await execute(
        """
        INSERT INTO omni_leads (id, workspace_id, contact_id, workflow_id, current_node_id, status, custom_fields)
        VALUES ($1, $2, NULL, $3, $4, 'active', '{}'::jsonb)
        """,
        lead_id,
        ctx.workspace_id,
        workflow_id,
        node_id,
    )

    # Run the entry node and publish its intent event(s) with lead_id + node_id
    # stamped, so the dispatcher resolves the channel and the muscle runs — the
    # same shape transition_worker._fire_node publishes mid-graph.
    node_ctx = noderegistry.NodeContext(
        workspace_id=ctx.workspace_id,
        workflow_id=str(workflow_id),
        node_id=node_id,
        config=node.get("config") or {},
        lead={"id": lead_id, "contact_id": None, "custom_fields": {}},
        correlation_id=correlation_id,
    )
    result = await execute_fn(node_ctx)

    published = 0
    for ev in result.events:
        payload = dict(ev.get("payload") or {})
        payload.setdefault("node_id", node_id)
        payload.setdefault("lead_id", lead_id)
        payload.setdefault("correlation_id", correlation_id)
        await bus.publish_event(
            workspace_id=ctx.workspace_id,
            event_type=ev["event_type"],
            # Re-home a workflow-scoped source intent onto the seed lead so the
            # dispatcher's lead path (entity_id == lead_id) resolves node_id from
            # current_node_id. Non-lead facts keep their own entity_type.
            entity_type="lead" if ev.get("entity_type") in (None, "workflow") else ev["entity_type"],
            entity_id=lead_id if ev.get("entity_type") in (None, "workflow") else ev.get("entity_id"),
            payload=payload,
            actor_user_id=ctx.user_id,
            correlation_id=correlation_id,
        )
        published += 1

    if result.error:
        # Source validated but refused (bad config). Surface it; the lead is left
        # for inspection rather than silently orphaned.
        log.warning("run_workflow %s entry node %s errored: %s", workflow_id, node_type, result.error)
        raise HTTPException(status_code=422, detail=f"entry node error: {result.error}")

    log.info(
        "ran workflow %s: seeded lead %s at %s (%s), published %d intent event(s)",
        workflow_id, lead_id, node_id, node_type, published,
    )
    return RunResponse(
        lead_id=uuid.UUID(lead_id),
        workflow_id=workflow_id,
        start_node_id=uuid.UUID(node_id),
        node_type=node_type,
        correlation_id=uuid.UUID(correlation_id),
        handle=result.handle,
        events_published=published,
    )
