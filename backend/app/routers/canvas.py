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
from app.services.campaign_composer import CampaignSpec, compile_campaign_spec
from app.services.graph_validation import validate_graph

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


async def _assert_campaign_spec_connections(spec: CampaignSpec, workspace_id: uuid.UUID) -> None:
    """Reject campaign specs that reference paid/API providers not connected here.

    Naukri and SearXNG are first-party/self-hosted sources and do not need an
    ``omni_connections`` row. Serper/company, Serper/people, and enrichment
    providers do: creating a graph with a made-up connection name looks
    successful but fails at runtime, which is much worse than blocking creation.
    """
    required: set[tuple[str, str]] = set()
    for source in spec.sources:
        if source.provider == "serper_search" and source.connection_name:
            required.add(("serper", source.connection_name))
        if source.provider == "leads_finder" and source.connection_name:
            required.add(("linkfinder", source.connection_name))
    if spec.people.provider == "serper_people" and spec.people.connection_name:
        required.add(("serper", spec.people.connection_name))
    for stage in spec.enrichment:
        required.add((stage.provider, stage.connection_name))
    for message in spec.messages:
        if not message.connection_name:
            continue
        if message.channel == "linkedin":
            required.add(("unipile", message.connection_name))
        elif message.channel == "email":
            required.add(("smtp", message.connection_name))

    for provider, name in sorted(required):
        row = await fetch_one(
            """
            SELECT 1
            FROM omni_connections
            WHERE workspace_id = $1 AND provider = $2 AND name = $3
            """,
            workspace_id,
            provider,
            name,
        )
        if not row:
            raise HTTPException(
                status_code=400,
                detail=f"{provider} connection {name!r} is not connected in this workspace",
            )


class GraphSave(BaseModel):
    nodes: list[GraphNodeIn] = Field(default_factory=list)
    edges: list[GraphEdgeIn] = Field(default_factory=list)


class GraphIssue(BaseModel):
    code: str
    message: str
    severity: Literal["error", "warning"]
    scope: Literal["structural", "config"]
    node_id: str | None = None
    edge_id: str | None = None


class GraphValidationOut(BaseModel):
    valid_for_save: bool
    valid_for_run: bool
    issues: list[GraphIssue]
    error_count: int
    warning_count: int


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


class GoalWorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    timezone: str = Field("UTC", max_length=64)
    metric: Literal["contacts", "qualified_leads", "companies", "replies"]
    target: int = Field(gt=0, le=100_000)
    audience: dict[str, Any] = Field(default_factory=dict)
    bounds: dict[str, Any] = Field(default_factory=dict)
    template_id: str | None = Field(default=None, max_length=120)


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


@router.post(
    "/workflows/from-goal",
    response_model=WorkflowDetail,
    status_code=201,
    summary="Create a goal-first workflow, optionally seeded from a starter plan",
)
async def create_from_goal(
    body: GoalWorkflowCreate,
    ctx: AuthContext = Depends(get_current_workspace),
) -> WorkflowDetail:
    from app.canvas_templates import TEMPLATES

    template = TEMPLATES.get(body.template_id) if body.template_id else None
    if body.template_id and not template:
        raise HTTPException(status_code=404, detail=f"unknown template {body.template_id!r}")

    key_to_id = {node.key: uuid.uuid4() for node in template.nodes} if template else {}
    async with acquire() as conn:
        async with conn.transaction():
            wf = await conn.fetchrow(
                "INSERT INTO omni_workflows (workspace_id, name, timezone) "
                "VALUES ($1, $2, $3) RETURNING *",
                ctx.workspace_id,
                body.name,
                body.timezone,
            )
            workflow_id = wf["id"]
            if template:
                for node in template.nodes:
                    await conn.execute(
                        """
                        INSERT INTO omni_workflow_nodes
                          (id, workspace_id, workflow_id, node_type, position_x, position_y, config)
                        VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                        """,
                        key_to_id[node.key],
                        ctx.workspace_id,
                        workflow_id,
                        node.node_type,
                        node.position_x,
                        node.position_y,
                        json.dumps(node.config),
                    )
                for edge in template.edges:
                    await conn.execute(
                        """
                        INSERT INTO omni_workflow_edges
                          (id, workspace_id, workflow_id, source_node_id, target_node_id,
                           source_handle, target_handle)
                        VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6)
                        """,
                        ctx.workspace_id,
                        workflow_id,
                        key_to_id[edge.source],
                        key_to_id[edge.target],
                        edge.source_handle,
                        edge.target_handle,
                    )
            await conn.execute(
                """
                INSERT INTO omni_campaign_objectives
                  (workspace_id, workflow_id, metric, target, audience, bounds, progress, status)
                VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,'{}'::jsonb,'pursuing')
                """,
                ctx.workspace_id,
                workflow_id,
                body.metric,
                body.target,
                json.dumps(body.audience),
                json.dumps(body.bounds),
            )
            nodes = await conn.fetch(
                "SELECT * FROM omni_workflow_nodes WHERE workflow_id=$1",
                workflow_id,
            )
            edges = await conn.fetch(
                "SELECT * FROM omni_workflow_edges WHERE workflow_id=$1",
                workflow_id,
            )
    return WorkflowDetail(
        workflow=WorkflowOut.model_validate(dict(wf)),
        nodes=[NodeOut.model_validate(dict(node)) for node in nodes],
        edges=[EdgeOut.model_validate(dict(edge)) for edge in edges],
    )


@router.post(
    "/workflows/from-spec",
    response_model=WorkflowDetail,
    status_code=201,
    summary="Create a workflow from a structured campaign spec",
    description=(
        "Compile a campaign-level spec (sources, enrichment stack, message sequence, "
        "and contact target) into the existing canvas graph. This is a higher-level "
        "authoring path; the resulting workflow remains fully editable on Canvas."
    ),
)
async def create_from_campaign_spec(
    body: CampaignSpec,
    ctx: AuthContext = Depends(get_current_workspace),
) -> WorkflowDetail:
    spec = body
    await _assert_campaign_spec_connections(spec, ctx.workspace_id)
    compiled = compile_campaign_spec(spec)
    key_to_id = {node.key: uuid.uuid4() for node in compiled.nodes}
    missing = [
        edge.source if edge.source not in key_to_id else edge.target
        for edge in compiled.edges
        if edge.source not in key_to_id or edge.target not in key_to_id
    ]
    if missing:
        raise HTTPException(status_code=500, detail=f"campaign compiler emitted unknown node key {missing[0]!r}")

    async with acquire() as conn:
        async with conn.transaction():
            wf = await conn.fetchrow(
                "INSERT INTO omni_workflows (workspace_id, name, timezone) "
                "VALUES ($1, $2, $3) RETURNING *",
                ctx.workspace_id,
                spec.name,
                spec.timezone,
            )
            workflow_id = wf["id"]
            for node in compiled.nodes:
                await conn.execute(
                    """
                    INSERT INTO omni_workflow_nodes
                      (id, workspace_id, workflow_id, node_type, position_x, position_y, config)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    key_to_id[node.key],
                    ctx.workspace_id,
                    workflow_id,
                    node.node_type,
                    node.position_x,
                    node.position_y,
                    json.dumps(node.config),
                )
            for edge in compiled.edges:
                await conn.execute(
                    """
                    INSERT INTO omni_workflow_edges
                      (id, workspace_id, workflow_id, source_node_id, target_node_id,
                       source_handle, target_handle)
                    VALUES (gen_random_uuid(), $1, $2, $3, $4, $5, $6)
                    """,
                    ctx.workspace_id,
                    workflow_id,
                    key_to_id[edge.source],
                    key_to_id[edge.target],
                    edge.source_handle,
                    edge.target_handle,
                )
            await conn.execute(
                """
                INSERT INTO omni_campaign_objectives
                  (workspace_id, workflow_id, metric, target, audience, bounds, progress, status)
                VALUES ($1,$2,$3,$4,$5::jsonb,$6::jsonb,'{}'::jsonb,'pursuing')
                """,
                ctx.workspace_id,
                workflow_id,
                compiled.objective["metric"],
                compiled.objective["target"],
                json.dumps(compiled.objective["audience"]),
                json.dumps(compiled.objective["bounds"]),
            )
            nodes = await conn.fetch(
                "SELECT * FROM omni_workflow_nodes WHERE workflow_id=$1",
                workflow_id,
            )
            edges = await conn.fetch(
                "SELECT * FROM omni_workflow_edges WHERE workflow_id=$1",
                workflow_id,
            )
    return WorkflowDetail(
        workflow=WorkflowOut.model_validate(dict(wf)),
        nodes=[NodeOut.model_validate(dict(node)) for node in nodes],
        edges=[EdgeOut.model_validate(dict(edge)) for edge in edges],
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


@router.delete(
    "/workflows/{workflow_id}/permanent",
    status_code=204,
    summary="Permanently delete an ARCHIVED workflow and all its data",
)
async def delete_workflow_permanent(
    workflow_id: uuid.UUID, ctx: AuthContext = Depends(get_current_workspace)
) -> None:
    """Hard-delete a workflow. Two-step by design: a workflow must be ARCHIVED
    first (the reversible step), so a live campaign can't be wiped by one click.

    Nodes/edges/objectives/sending-account pool FK omni_workflows ON DELETE
    CASCADE, so deleting the workflow row removes them. omni_leads does NOT (it
    FKs only workspaces, carrying a plain workflow_id), so its rows would be
    orphaned — delete them explicitly first. (omni_tasks is contact-scoped, not
    workflow-scoped, so it's untouched here.) All in one transaction so a failure
    leaves nothing half-deleted."""
    async with acquire() as conn:
        async with conn.transaction():
            row = await conn.fetchrow(
                "SELECT status FROM omni_workflows WHERE id = $1 AND workspace_id = $2",
                workflow_id, ctx.workspace_id,
            )
            if not row:
                raise HTTPException(status_code=404, detail="workflow not found")
            if row["status"] != "archived":
                raise HTTPException(
                    status_code=409,
                    detail="archive the campaign before deleting it permanently",
                )
            # Leads carry a plain workflow_id (no FK cascade) — remove explicitly.
            await conn.execute(
                "DELETE FROM omni_leads WHERE workflow_id = $1 AND workspace_id = $2",
                workflow_id, ctx.workspace_id,
            )
            # Cascade handles nodes/edges/objectives/pool.
            await conn.execute(
                "DELETE FROM omni_workflows WHERE id = $1 AND workspace_id = $2",
                workflow_id, ctx.workspace_id,
            )


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


async def _graph_validation(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    *,
    has_audience: bool = False,
) -> GraphValidationOut:
    connection_rows = await fetch_all("SELECT provider, name FROM omni_connections")
    result = validate_graph(
        nodes,
        edges,
        connections={(str(row["provider"]), str(row["name"])) for row in connection_rows},
        has_audience=has_audience,
    )
    return GraphValidationOut.model_validate(result)


async def _workflow_has_audience(workflow_id: uuid.UUID) -> bool:
    """OUTBOUND-FIRST-001: does this campaign have an attached audience? An
    outbound-first root (a channel node with no source upstream) is runnable
    only when contacts are attached to reach."""
    row = await fetch_one(
        "SELECT EXISTS(SELECT 1 FROM omni_campaign_audience WHERE workflow_id=$1) AS has", workflow_id
    )
    return bool(row and row["has"])


@router.get(
    "/workflows/{workflow_id}/validation",
    response_model=GraphValidationOut,
    summary="Explain whether a saved workflow is structurally sound and runnable",
)
async def validate_saved_graph(
    workflow_id: uuid.UUID,
    _: AuthContext = Depends(get_current_workspace),
) -> GraphValidationOut:
    workflow = await fetch_one("SELECT id FROM omni_workflows WHERE id=$1", workflow_id)
    if not workflow:
        raise HTTPException(status_code=404, detail="workflow not found")
    nodes = await fetch_all("SELECT * FROM omni_workflow_nodes WHERE workflow_id=$1", workflow_id)
    edges = await fetch_all("SELECT * FROM omni_workflow_edges WHERE workflow_id=$1", workflow_id)
    has_audience = await _workflow_has_audience(workflow_id)
    return await _graph_validation(
        [dict(node) for node in nodes], [dict(edge) for edge in edges], has_audience=has_audience
    )


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
    validation = await _graph_validation(
        [node.model_dump() for node in body.nodes],
        [edge.model_dump() for edge in body.edges],
    )
    if not validation.valid_for_save:
        raise HTTPException(
            status_code=422,
            detail={
                "message": "The graph has structural errors and was not saved.",
                "issues": [issue.model_dump() for issue in validation.issues],
            },
        )

    async with acquire() as conn:
        async with conn.transaction():
            wf = await conn.fetchrow("SELECT * FROM omni_workflows WHERE id = $1", workflow_id)
            if not wf:
                raise HTTPException(status_code=404, detail="workflow not found")

            # Replace-all: wipe then re-insert. Edges first (FK-free here, but keep order tidy).
            await conn.execute("DELETE FROM omni_workflow_edges WHERE workflow_id = $1", workflow_id)
            await conn.execute("DELETE FROM omni_workflow_nodes WHERE workflow_id = $1", workflow_id)

            for n in body.nodes:
                await conn.execute(
                    """
                    INSERT INTO omni_workflow_nodes
                      (id, workspace_id, workflow_id, node_type, position_x, position_y, config)
                    VALUES ($1, $2, $3, $4, $5, $6, $7::jsonb)
                    """,
                    n.id, ctx.workspace_id, workflow_id, n.node_type, n.position_x, n.position_y, n.config,
                )
            for e in body.edges:
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
    sources_started: int = 1
    sources_failed: int = 0
    failures: list[str] = Field(default_factory=list)
    lead_ids: list[uuid.UUID] = Field(default_factory=list)
    start_node_ids: list[uuid.UUID] = Field(default_factory=list)
    node_types: list[str] = Field(default_factory=list)


@router.post(
    "/workflows/{workflow_id}/run",
    response_model=RunResponse,
    summary="Run a workflow — start every source as one correlated run",
    description=(
        "Creates one seed lead per starting source and fires those sources under one "
        "correlation id, publishing their intent events so the dispatcher routes "
        "the muscle commands and the pipeline begins. This is the missing trigger: "
        "without it, workflows are inert CRUD and no lead is ever produced. The "
        "sources' discovered entities fan out into child leads via flow.for_each, "
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

    validation = await validate_saved_graph(workflow_id, ctx)
    if not validation.valid_for_run:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Fix the campaign issues before running it.",
                "issues": [issue.model_dump() for issue in validation.issues],
            },
        )

    start_node = None
    if body.start_node_id:
        start_node = await fetch_one(
            "SELECT id, node_type, config FROM omni_workflow_nodes WHERE id = $1 AND workflow_id = $2 AND workspace_id = $3",
            body.start_node_id, workflow_id, ctx.workspace_id,
        )
        if not start_node:
            raise HTTPException(status_code=404, detail="start_node_id not in this workflow")

    if start_node:
        outcomes = [
            await runner.seed_and_run(
                workspace_id=ctx.workspace_id,
                workflow_id=str(workflow_id),
                start_node=dict(start_node),
                actor_user_id=ctx.user_id,
            )
        ]
    else:
        outcomes = await runner.seed_and_run_many(
            workspace_id=ctx.workspace_id,
            workflow_id=str(workflow_id),
            actor_user_id=ctx.user_id,
        )
    failures = [outcome for outcome in outcomes if outcome.error]
    successes = [outcome for outcome in outcomes if not outcome.error]
    if not successes:
        error = failures[0].error if failures else "workflow has no entry node"
        status_code = 400 if failures and not failures[0].lead_id else 422
        raise HTTPException(status_code=status_code, detail=f"entry node error: {error}")
    # CAMPAIGN-STATUS-001: a campaign's status was only ever 'draft' (on create)
    # or 'archived' — nothing flipped it 'active' when a run actually started, so a
    # running campaign read "Draft" forever in the UI. On a successful run, promote
    # a draft to active. Only from 'draft' — never reactivate an 'archived' campaign
    # or override a deliberate 'paused' — so this reflects "it has run" without
    # clobbering operator intent.
    await execute(
        "UPDATE omni_workflows SET status = 'active', updated_at = NOW() "
        "WHERE id = $1 AND workspace_id = $2 AND status = 'draft'",
        workflow_id,
        ctx.workspace_id,
    )

    outcome = successes[0]
    return RunResponse(
        lead_id=uuid.UUID(outcome.lead_id),
        workflow_id=workflow_id,
        start_node_id=uuid.UUID(outcome.node_id),
        node_type=outcome.node_type,
        correlation_id=uuid.UUID(outcome.correlation_id),
        handle=outcome.handle,
        events_published=sum(item.events_published for item in successes),
        sources_started=len(successes),
        sources_failed=len(failures),
        failures=[
            f"{item.node_type or 'unknown'}: {item.error or 'failed to start'}" for item in failures
        ],
        lead_ids=[uuid.UUID(item.lead_id) for item in successes],
        start_node_ids=[uuid.UUID(item.node_id) for item in successes],
        node_types=[item.node_type for item in successes],
    )


# ── Campaign audience (OUTBOUND-FIRST-001) ─────────────────────────────────────
# The recipients an outbound-first campaign reaches. Attaching contacts here is
# what lets a campaign START with an outbound step (invite/DM/email a known list)
# instead of always discovering leads from a source. The run enrolls one lead per
# attached contact (see app.execution.run.seed_and_run_audience).


class AudienceContactOut(BaseModel):
    contact_id: uuid.UUID
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    linkedin_url: str | None = None
    company: str | None = None
    added_at: datetime


class AudienceAdd(BaseModel):
    contact_ids: list[uuid.UUID] = Field(min_length=1, max_length=10_000)


class AudienceMutationOut(BaseModel):
    added: int = 0
    removed: int = 0
    total: int


async def _audience_total(workflow_id: uuid.UUID, workspace_id: str) -> int:
    row = await fetch_one(
        "SELECT count(*) AS n FROM omni_campaign_audience WHERE workflow_id=$1 AND workspace_id=$2",
        workflow_id, workspace_id,
    )
    return int(row["n"]) if row else 0


@router.get(
    "/workflows/{workflow_id}/audience",
    response_model=list[AudienceContactOut],
    summary="List the contacts attached to a campaign as its outbound audience",
)
async def list_audience(
    workflow_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current_workspace),
) -> list[AudienceContactOut]:
    rows = await fetch_all(
        """
        SELECT a.contact_id, a.added_at,
               c.first_name, c.last_name, c.email, c.linkedin_url, c.company
        FROM omni_campaign_audience a
        JOIN omni_contacts c ON c.id = a.contact_id
        WHERE a.workflow_id=$1 AND a.workspace_id=$2
        ORDER BY a.added_at DESC
        """,
        workflow_id, ctx.workspace_id,
    )
    return [AudienceContactOut.model_validate(dict(r)) for r in rows]


@router.post(
    "/workflows/{workflow_id}/audience",
    response_model=AudienceMutationOut,
    status_code=201,
    summary="Attach contacts to a campaign's outbound audience",
    description=(
        "Adds the given contacts as recipients of this campaign. Idempotent — a "
        "contact already attached is skipped. Only contacts in the caller's "
        "workspace are added (a foreign id is silently ignored). The campaign can "
        "then START with an outbound step that reaches this audience."
    ),
)
async def add_audience(
    workflow_id: uuid.UUID,
    body: AudienceAdd,
    ctx: AuthContext = Depends(get_current_workspace),
) -> AudienceMutationOut:
    wf = await fetch_one(
        "SELECT id FROM omni_workflows WHERE id=$1 AND workspace_id=$2", workflow_id, ctx.workspace_id
    )
    if not wf:
        raise HTTPException(status_code=404, detail="workflow not found")
    # Only attach contacts that exist in this workspace (RLS already scopes the
    # SELECT; the INSERT…SELECT makes a foreign/absent id a no-op instead of an FK error).
    ids = [str(cid) for cid in body.contact_ids]
    result = await execute(
        """
        INSERT INTO omni_campaign_audience (workspace_id, workflow_id, contact_id)
        SELECT $1, $2, c.id FROM omni_contacts c
        WHERE c.workspace_id=$1 AND c.id = ANY($3::uuid[])
        ON CONFLICT (workflow_id, contact_id) DO NOTHING
        """,
        ctx.workspace_id, workflow_id, ids,
    )
    added = int(str(result).split()[-1]) if result else 0
    return AudienceMutationOut(added=added, total=await _audience_total(workflow_id, ctx.workspace_id))


@router.delete(
    "/workflows/{workflow_id}/audience/{contact_id}",
    response_model=AudienceMutationOut,
    summary="Remove a contact from a campaign's outbound audience",
)
async def remove_audience(
    workflow_id: uuid.UUID,
    contact_id: uuid.UUID,
    ctx: AuthContext = Depends(get_current_workspace),
) -> AudienceMutationOut:
    result = await execute(
        "DELETE FROM omni_campaign_audience WHERE workflow_id=$1 AND contact_id=$2 AND workspace_id=$3",
        workflow_id, contact_id, ctx.workspace_id,
    )
    removed = int(str(result).split()[-1]) if result else 0
    return AudienceMutationOut(removed=removed, total=await _audience_total(workflow_id, ctx.workspace_id))
