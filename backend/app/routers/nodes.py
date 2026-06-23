"""Node registry HTTP surface.

  GET  /nodes               list every registered node's manifest
  GET  /nodes/{type}        one manifest
  POST /nodes/{type}/execute  run a node ad-hoc (for testing / canvas previews)

In production the canvas runtime calls ``execute`` directly via the
Python API — this HTTP route is for operators inspecting nodes and for
the frontend to render config forms from manifests.
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.nodes import NodeContext, get, manifests
from app.services.bus import publish_event

router = APIRouter()


class NodeManifestOut(BaseModel):
    type: str
    category: str
    summary: str
    config_schema: dict[str, Any]
    output_handles: list[dict[str, str]]
    capabilities: list[str]
    side_effect: str
    icon: str
    display_name: str
    primary_fields: list[str]
    advanced_fields: list[str]
    visible_in_palette: bool


class NodeExecuteRequest(BaseModel):
    config: dict[str, Any] = Field(default_factory=dict, description="Node-specific config (validated against the manifest's config_schema)")
    lead: dict[str, Any] = Field(default_factory=dict, description="Lead context (id, contact_id, custom fields, …)")
    workflow_id: uuid.UUID | None = None
    node_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None


class NodeExecuteResponse(BaseModel):
    handle: str
    telemetry: dict[str, Any]
    events_published: int = Field(description="Number of events published to omni.events")
    error: str | None


@router.get(
    "",
    response_model=list[NodeManifestOut],
    summary="List every registered node type",
    description="Returns one manifest per node type. The frontend renders config forms directly from each manifest's config_schema.",
)
async def list_nodes(_: AuthContext = Depends(get_current_workspace)) -> list[NodeManifestOut]:
    return [NodeManifestOut(**m.to_openapi()) for m in manifests()]


@router.get("/{node_type}", response_model=NodeManifestOut, summary="Fetch one node manifest")
async def get_node(node_type: str, _: AuthContext = Depends(get_current_workspace)) -> NodeManifestOut:
    try:
        manifest, _fn = get(node_type)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="unknown node type") from e
    return NodeManifestOut(**manifest.to_openapi())


@router.post(
    "/{node_type}/execute",
    response_model=NodeExecuteResponse,
    summary="Execute a node ad-hoc",
    description=(
        "Runs a node outside of a workflow — useful for canvas previews, "
        "testing config, and dry-running an integration. Any events the "
        "node produces ARE appended to the workspace's event log."
    ),
)
async def execute_node(
    node_type: str,
    body: NodeExecuteRequest,
    ctx: AuthContext = Depends(get_current_workspace),
) -> NodeExecuteResponse:
    try:
        _manifest, fn = get(node_type)
    except KeyError as e:
        raise HTTPException(status_code=404, detail="unknown node type") from e

    node_ctx = NodeContext(
        workspace_id=ctx.workspace_id,
        workflow_id=str(body.workflow_id) if body.workflow_id else None,
        node_id=str(body.node_id) if body.node_id else None,
        config=body.config,
        lead=body.lead,
        correlation_id=str(body.correlation_id) if body.correlation_id else None,
    )
    result = await fn(node_ctx)

    # Nodes return events the runtime should publish — we own the bus call
    # so node implementations stay pure (testable without Kafka running).
    for ev in result.events:
        await publish_event(
            workspace_id=ctx.workspace_id,
            event_type=ev["event_type"],
            entity_type=ev["entity_type"],
            entity_id=ev.get("entity_id"),
            payload=ev.get("payload") or {},
            actor_user_id=ctx.user_id,
            correlation_id=node_ctx.correlation_id,
        )
    return NodeExecuteResponse(
        handle=result.handle,
        telemetry=result.telemetry,
        events_published=len(result.events),
        error=result.error,
    )
