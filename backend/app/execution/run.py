"""Shared workflow seed-and-run — the ONE place a workflow is kicked off.

Resolving the entry node, seeding a root lead at it, firing the node, and
publishing its intent events is the exact sequence three callers need:
  - POST /canvas/workflows/{id}/run        (operator presses Run)
  - the objective worker's re-seed          (goal pursuit widens + re-runs)
  - (future) scheduled / triggered runs

It used to be copy-pasted in each, which drifts. This module owns it. The HTTP
router wraps the result in its response + raises on error; the worker logs.

A run seeds a ROOT lead (no parent_lead_id) at a source node; the source fans
out into child leads via flow.for_each. The root lead parks as the join barrier
and terminalizes when the whole tree finishes — which is what the objective
worker keys off (see app.execution.objective_worker).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from typing import Any

import app.nodes as noderegistry
from app.db import execute, fetch_all, fetch_one, system_scope
from app.services import bus

log = logging.getLogger("run")


@dataclass(frozen=True)
class RunOutcome:
    lead_id: str
    node_id: str
    node_type: str
    correlation_id: str
    handle: str
    events_published: int
    error: str | None = None


async def entry_node(workflow_id: str, workspace_id: str) -> dict | None:
    """The workflow's entry node — the one no edge targets. Prefer a source.*
    node when several qualify (parallel sources), else the first by position."""
    async with system_scope():
        nodes = await fetch_all(
            "SELECT id, node_type, config FROM omni_workflow_nodes "
            "WHERE workflow_id=$1 AND workspace_id=$2 ORDER BY position_y, position_x",
            workflow_id, workspace_id,
        )
        if not nodes:
            return None
        targeted = await fetch_all(
            "SELECT DISTINCT target_node_id FROM omni_workflow_edges WHERE workflow_id=$1 AND workspace_id=$2",
            workflow_id, workspace_id,
        )
    targeted_ids = {str(r["target_node_id"]) for r in targeted}
    roots = [n for n in nodes if str(n["id"]) not in targeted_ids]
    if not roots:
        return None
    return next((n for n in roots if str(n["node_type"]).startswith("source.")), roots[0])


async def seed_and_run(
    *,
    workspace_id: str,
    workflow_id: str,
    start_node: dict | None = None,
    config_overrides: dict[str, Any] | None = None,
    actor_user_id: str | None = None,
    correlation_id: str | None = None,
) -> RunOutcome:
    """Seed a root lead at the entry (or given) node, fire it, publish its
    intents. Returns a RunOutcome (``error`` set if the entry node errored —
    the seed lead is marked 'errored' so it isn't stranded 'active').

    ``config_overrides`` lets a re-run widen the entry node's config (the
    objective worker advances the sourcing keyword) without mutating the stored
    node config — the override is merged only for this firing.
    """
    node = start_node or await entry_node(workflow_id, workspace_id)
    if not node:
        return RunOutcome("", "", "", "", "", 0, error="workflow has no entry node")

    node_type = str(node["node_type"])
    try:
        _manifest, execute_fn = noderegistry.get(node_type)
    except KeyError:
        return RunOutcome("", str(node["id"]), node_type, "", "", 0, error=f"entry node {node_type!r} not registered")

    lead_id = str(uuid.uuid4())
    node_id = str(node["id"])
    correlation_id = correlation_id or str(uuid.uuid4())
    merged_config = {**(node.get("config") or {}), **(config_overrides or {})}

    # Seed the root lead at the entry node (no contact — the source discovers
    # entities that fan out into children).
    async with system_scope():
        await execute(
            "INSERT INTO omni_leads (id, workspace_id, contact_id, workflow_id, current_node_id, status, custom_fields) "
            "VALUES ($1, $2, NULL, $3, $4, 'active', '{}'::jsonb)",
            lead_id, workspace_id, workflow_id, node_id,
        )

    node_ctx = noderegistry.NodeContext(
        workspace_id=workspace_id,
        workflow_id=str(workflow_id),
        node_id=node_id,
        config=merged_config,
        lead={"id": lead_id, "contact_id": None, "custom_fields": {}},
        correlation_id=correlation_id,
    )
    result = await execute_fn(node_ctx)

    # SM-3: inspect error BEFORE publishing. An errored entry node ships nothing
    # and the seed lead is marked 'errored' (not stranded 'active' at the node).
    if result.error:
        async with system_scope():
            await execute(
                "UPDATE omni_leads SET status='errored', current_node_id=NULL, updated_at=NOW() "
                "WHERE id=$1 AND workspace_id=$2",
                lead_id, workspace_id,
            )
        log.warning("seed_and_run %s entry %s errored: %s", workflow_id, node_type, result.error)
        return RunOutcome(lead_id, node_id, node_type, correlation_id, result.handle, 0, error=result.error)

    published = 0
    for ev in result.events:
        payload = dict(ev.get("payload") or {})
        payload.setdefault("node_id", node_id)
        payload.setdefault("lead_id", lead_id)
        payload.setdefault("correlation_id", correlation_id)
        # Re-home a workflow-scoped source intent onto the seed lead so the
        # dispatcher's lead path resolves node_id from current_node_id.
        await bus.publish_event(
            workspace_id=workspace_id,
            event_type=ev["event_type"],
            entity_type="lead" if ev.get("entity_type") in (None, "workflow") else ev["entity_type"],
            entity_id=lead_id if ev.get("entity_type") in (None, "workflow") else ev.get("entity_id"),
            payload=payload,
            actor_user_id=actor_user_id,
            correlation_id=correlation_id,
        )
        published += 1

    log.info("seed_and_run %s: lead %s at %s (%s), published %d intents", workflow_id, lead_id, node_id, node_type, published)
    return RunOutcome(lead_id, node_id, node_type, correlation_id, result.handle, published)


async def workflow_exists(workflow_id: str, workspace_id: str) -> bool:
    async with system_scope():
        row = await fetch_one(
            "SELECT 1 FROM omni_workflows WHERE id=$1 AND workspace_id=$2", workflow_id, workspace_id
        )
    return row is not None
