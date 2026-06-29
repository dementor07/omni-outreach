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

import json
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


async def entry_nodes(workflow_id: str, workspace_id: str) -> list[dict]:
    """All graph roots in stable visual order.

    Valid runnable graphs contain only source roots. Keeping this primitive
    plural makes multi-source execution explicit instead of silently choosing
    whichever source happens to sort first.
    """
    async with system_scope():
        nodes = await fetch_all(
            "SELECT id, node_type, config FROM omni_workflow_nodes "
            "WHERE workflow_id=$1 AND workspace_id=$2 ORDER BY position_y, position_x",
            workflow_id, workspace_id,
        )
        if not nodes:
            return []
        targeted = await fetch_all(
            "SELECT DISTINCT target_node_id FROM omni_workflow_edges WHERE workflow_id=$1 AND workspace_id=$2",
            workflow_id, workspace_id,
        )
    targeted_ids = {str(r["target_node_id"]) for r in targeted}
    return [n for n in nodes if str(n["id"]) not in targeted_ids]


async def entry_node(workflow_id: str, workspace_id: str) -> dict | None:
    """Back-compatible single-entry accessor used by focused re-runs."""
    roots = await entry_nodes(workflow_id, workspace_id)
    return roots[0] if roots else None


def _is_source_node(node_type: str) -> bool:
    return str(node_type or "").startswith("source.")


async def _audience_contacts(workflow_id: str, workspace_id: str) -> list[dict]:
    """OUTBOUND-FIRST-001: the contacts attached to this campaign as its
    audience, with the identity an outbound channel needs to reach them.
    Empty when no audience is bound (the source-first case)."""
    async with system_scope():
        rows = await fetch_all(
            """
            SELECT c.id, c.first_name, c.last_name, c.email, c.linkedin_url,
                   c.phone, c.company, c.headline
            FROM omni_campaign_audience a
            JOIN omni_contacts c ON c.id = a.contact_id
            WHERE a.workflow_id=$1 AND a.workspace_id=$2
            ORDER BY a.added_at
            """,
            workflow_id, workspace_id,
        )
    return [dict(r) for r in rows]


def _contact_to_lead_fields(contact: dict) -> dict[str, Any]:
    """The recipient identity an outbound lead carries in custom_fields so the
    dispatcher/muscle can resolve who to message — mirrors what a source writes
    onto a discovered person."""
    keys = ("first_name", "last_name", "email", "linkedin_url", "phone", "company", "headline")
    return {k: contact[k] for k in keys if contact.get(k)}


async def seed_and_run_audience(
    *,
    workspace_id: str,
    workflow_id: str,
    start_node: dict,
    contacts: list[dict],
    actor_user_id: str | None = None,
    correlation_id: str | None = None,
) -> list[RunOutcome]:
    """OUTBOUND-FIRST-001: enroll one lead PER audience contact at an outbound
    entry node — each lead bound to its contact_id and carrying the recipient's
    identity — then fire the node for each. This is the outbound-first analogue
    of a source seeding discovered leads: here the "discovery" is the attached
    audience. Returns one RunOutcome per contact."""
    run_correlation_id = correlation_id or str(uuid.uuid4())
    node_type = str(start_node["node_type"])
    node_id = str(start_node["id"])
    try:
        _manifest, execute_fn = noderegistry.get(node_type)
    except KeyError:
        return [RunOutcome("", node_id, node_type, run_correlation_id, "", 0, error=f"entry node {node_type!r} not registered")]

    outcomes: list[RunOutcome] = []
    for contact in contacts:
        lead_id = str(uuid.uuid4())
        contact_id = str(contact["id"])
        lead_fields = {
            **_contact_to_lead_fields(contact),
            "_run_correlation_id": run_correlation_id,
            "_audience_contact_id": contact_id,
        }
        async with system_scope():
            await execute(
                "INSERT INTO omni_leads (id, workspace_id, contact_id, workflow_id, current_node_id, status, custom_fields) "
                "VALUES ($1, $2, $3, $4, $5, 'active', $6::jsonb)",
                lead_id, workspace_id, contact_id, workflow_id, node_id, json.dumps(lead_fields),
            )
        node_ctx = noderegistry.NodeContext(
            workspace_id=workspace_id,
            workflow_id=str(workflow_id),
            node_id=node_id,
            config=dict(start_node.get("config") or {}),
            lead={"id": lead_id, "contact_id": contact_id, "custom_fields": lead_fields},
            correlation_id=run_correlation_id,
        )
        result = await execute_fn(node_ctx)
        if result.error:
            async with system_scope():
                await execute(
                    "UPDATE omni_leads SET status='errored', current_node_id=NULL, updated_at=NOW() "
                    "WHERE id=$1 AND workspace_id=$2",
                    lead_id, workspace_id,
                )
            outcomes.append(RunOutcome(lead_id, node_id, node_type, run_correlation_id, result.handle, 0, error=result.error))
            continue
        published = 0
        for ev in result.events:
            payload = dict(ev.get("payload") or {})
            payload.setdefault("node_id", node_id)
            payload.setdefault("lead_id", lead_id)
            payload.setdefault("correlation_id", run_correlation_id)
            await bus.publish_event(
                workspace_id=workspace_id,
                event_type=ev["event_type"],
                entity_type="lead" if ev.get("entity_type") in (None, "workflow") else ev["entity_type"],
                entity_id=lead_id if ev.get("entity_type") in (None, "workflow") else ev.get("entity_id"),
                payload=payload,
                actor_user_id=actor_user_id,
                correlation_id=run_correlation_id,
            )
            published += 1
        outcomes.append(RunOutcome(lead_id, node_id, node_type, run_correlation_id, result.handle, published))
    log.info("seed_and_run_audience %s: enrolled %d audience leads at %s (%s)", workflow_id, len(outcomes), node_id, node_type)
    return outcomes


async def seed_and_run_many(
    *,
    workspace_id: str,
    workflow_id: str,
    start_nodes: list[dict] | None = None,
    actor_user_id: str | None = None,
    correlation_id: str | None = None,
) -> list[RunOutcome]:
    """Fire every root source as one logical campaign run.

    Each source receives its own seed lead (preserving lineage and provenance)
    while all roots share one correlation id for tracing, cost, and objective
    accounting. Sources are fired in stable order; their external work remains
    asynchronous through the normal intent bus.
    """
    roots = start_nodes if start_nodes is not None else await entry_nodes(workflow_id, workspace_id)
    if not roots:
        return [RunOutcome("", "", "", "", "", 0, error="workflow has no entry node")]
    run_correlation_id = correlation_id or str(uuid.uuid4())

    # OUTBOUND-FIRST-001: a non-source entry node (an outbound channel rooting the
    # campaign) has no upstream to supply leads — it reaches an ATTACHED audience.
    # Fetch it once; each non-source root enrolls one lead per audience contact.
    # Source roots keep the discover-and-fan-out empty-root seeding unchanged.
    has_outbound_root = any(not _is_source_node(r["node_type"]) for r in roots)
    audience = await _audience_contacts(workflow_id, workspace_id) if has_outbound_root else []

    outcomes: list[RunOutcome] = []
    for index, root in enumerate(roots):
        if not _is_source_node(root["node_type"]):
            # Outbound-first root → enroll the audience (one lead per contact).
            if not audience:
                outcomes.append(
                    RunOutcome(
                        "", str(root["id"]), str(root["node_type"]), run_correlation_id, "", 0,
                        error="outbound entry node has no attached audience to reach",
                    )
                )
                continue
            outcomes.extend(
                await seed_and_run_audience(
                    workspace_id=workspace_id,
                    workflow_id=workflow_id,
                    start_node=root,
                    contacts=audience,
                    actor_user_id=actor_user_id,
                    correlation_id=run_correlation_id,
                )
            )
            continue
        outcomes.append(
            await seed_and_run(
                workspace_id=workspace_id,
                workflow_id=workflow_id,
                start_node=root,
                actor_user_id=actor_user_id,
                correlation_id=run_correlation_id,
                run_source_count=len(roots),
                run_source_index=index,
            )
        )
    return outcomes


async def seed_and_run(
    *,
    workspace_id: str,
    workflow_id: str,
    start_node: dict | None = None,
    config_overrides: dict[str, Any] | None = None,
    actor_user_id: str | None = None,
    correlation_id: str | None = None,
    run_source_count: int = 1,
    run_source_index: int = 0,
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
    run_metadata = {
        "_run_correlation_id": correlation_id,
        "_run_source_count": run_source_count,
        "_run_source_index": run_source_index,
    }

    # Seed the root lead at the entry node (no contact — the source discovers
    # entities that fan out into children).
    async with system_scope():
        await execute(
            "INSERT INTO omni_leads (id, workspace_id, contact_id, workflow_id, current_node_id, status, custom_fields) "
            "VALUES ($1, $2, NULL, $3, $4, 'active', $5::jsonb)",
            lead_id, workspace_id, workflow_id, node_id, json.dumps(run_metadata),
        )

    node_ctx = noderegistry.NodeContext(
        workspace_id=workspace_id,
        workflow_id=str(workflow_id),
        node_id=node_id,
        config=merged_config,
        lead={"id": lead_id, "contact_id": None, "custom_fields": run_metadata},
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
