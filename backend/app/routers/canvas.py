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

import uuid
from datetime import datetime
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import execute, fetch_all, fetch_one

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
