import json
import re
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

# Lead fields the renderer can substitute (mirrors renderer.render + lead columns).
# Any {{var}} outside this set must be declared via an earlier action_data_transform
# or action_ai_compose node (which writes to extra_data).
_LEAD_FIELDS = frozenset({
    "id", "first_name", "last_name", "firstname", "lastname", "email", "phone",
    "headline", "company", "company_short_name", "linkedin_url", "location",
    "source", "current_step", "ai_draft",
})

_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


def _collect_vars(value) -> set[str]:
    """Walk a node.data structure and return every {{var}} referenced in any string field."""
    found: set[str] = set()
    if isinstance(value, str):
        found.update(_VAR_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= _collect_vars(v)
    elif isinstance(value, list):
        for v in value:
            found |= _collect_vars(v)
    return found


def _declared_variables(nodes: list["NodeCreate"]) -> set[str]:
    """Variables a node will write into lead.extra_data — usable downstream."""
    declared: set[str] = set()
    for n in nodes:
        d = n.data or {}
        if n.node_type == "action_data_transform":
            name = str(d.get("variable_name", "")).strip()
            if name:
                declared.add(name)
        elif n.node_type == "action_ai_compose":
            name = str(d.get("target_variable", "ai_draft")).strip() or "ai_draft"
            declared.add(name)
    return declared

router = APIRouter()

NodeType = Literal[
    "trigger_start",
    "action_linkedin_invite",
    "action_linkedin_dm",
    "action_linkedin_inmail",
    "action_linkedin_profile_view",
    "action_email",
    "action_whatsapp",
    "action_sms",
    "action_instagram",
    "action_telegram",
    "action_voice",
    "action_webhook",
    "action_add_tag",
    "action_remove_tag",
    "action_enrich",
    "action_data_transform",
    "action_ai_compose",
    "action_agent",
    "action_lead_gen_pull",
    "action_csv_import",
    "condition_replied",
    "condition_linkedin_distance",
    "condition_tag_exists",
    "condition_ai_screen",
    "condition_lead_source",
    "condition_has_field",
    "condition_field_equals",
    "condition_lead_quota_reached",
    "condition_lead_quality_score",
    "condition_reply_intent",
    "human_approval",
    "action_hot_lead_alert",
    "event_invite_accepted",
    "event_email_opened",
    "event_link_clicked",
    "event_webhook_received",
    "event_leads_imported",
    "control_parallel_fork",
    "control_race",
    "delay",
    "wait_until",
    "split",
    "goal",
    "sticky_note",
    "end",
]


class NodeCreate(BaseModel):
    id: str | None = None  # React Flow ID
    node_type: NodeType
    position_x: float
    position_y: float
    data: dict = {}


class EdgeCreate(BaseModel):
    id: str | None = None
    source_node_id: str
    target_node_id: str
    source_handle: str = "default"
    target_handle: str = "default"


class SequenceGraph(BaseModel):
    campaign_id: str
    nodes: list[NodeCreate]
    edges: list[EdgeCreate]


@router.get("/{campaign_id}")
async def get_graph(campaign_id: str, user_id: str = Depends(get_current_user)):
    nodes = await fetch_all(
        "SELECT * FROM sequence_nodes WHERE campaign_id = $1",
        campaign_id,
    )
    edges = await fetch_all(
        "SELECT * FROM sequence_edges WHERE campaign_id = $1",
        campaign_id,
    )
    return {"nodes": nodes, "edges": edges}


@router.post("/save")
async def save_graph(body: SequenceGraph, user_id: str = Depends(get_current_user)):
    # Verify campaign exists
    campaign = await fetch_one("SELECT id FROM campaigns WHERE id=$1", body.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    # Variable validation: every {{var}} referenced by a node must resolve to either
    # a known lead field or a variable declared by an earlier action_data_transform /
    # action_ai_compose node. Order-agnostic check (graph may be non-linear).
    declared = _declared_variables(body.nodes)
    allowed = _LEAD_FIELDS | declared
    unresolved: dict[str, list[str]] = {}
    for n in body.nodes:
        refs = _collect_vars(n.data)
        bad = sorted(v for v in refs if v not in allowed)
        if bad:
            unresolved[n.id or n.node_type] = bad
    if unresolved:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "unresolved_variables",
                "message": "One or more nodes reference variables that no lead field or upstream node provides.",
                "unresolved": unresolved,
                "allowed_lead_fields": sorted(_LEAD_FIELDS),
                "declared_by_nodes": sorted(declared),
            },
        )

    # UPSERT semantics. We can't wipe-and-replace sequence_nodes because
    # queue.node_id has a FK back to it — any in-flight task would block
    # the DELETE (ForeignKeyViolation) and lock operators out of saving
    # their own graph. Instead:
    #   1. Each posted node carries its own client-stable UUID in node.id.
    #   2. If a row exists with that id, UPDATE in place. Otherwise INSERT.
    #   3. Then DELETE only nodes whose ids no longer appear in the payload.
    # Edges have no inbound FK so we still wipe+reinsert them.

    import uuid as _uuid

    def _is_uuid(s: str | None) -> bool:
        if not s:
            return False
        try:
            _uuid.UUID(str(s))
            return True
        except (ValueError, AttributeError, TypeError):
            return False

    node_id_map: dict[str, str] = {}
    posted_ids: set[str] = set()

    for node in body.nodes:
        if _is_uuid(node.id):
            # UPSERT keyed on the client-supplied UUID. Postgres ON CONFLICT
            # path keeps queue/sequence_edges FK references intact.
            row = await fetch_one(
                """
                INSERT INTO sequence_nodes (id, campaign_id, node_type, position_x, position_y, data)
                VALUES ($1, $2, $3, $4, $5, $6)
                ON CONFLICT (id) DO UPDATE
                  SET node_type   = EXCLUDED.node_type,
                      position_x  = EXCLUDED.position_x,
                      position_y  = EXCLUDED.position_y,
                      data        = EXCLUDED.data
                RETURNING id
                """,
                node.id,
                body.campaign_id,
                node.node_type,
                node.position_x,
                node.position_y,
                json.dumps(node.data),
            )
        else:
            row = await fetch_one(
                """
                INSERT INTO sequence_nodes (campaign_id, node_type, position_x, position_y, data)
                VALUES ($1, $2, $3, $4, $5)
                RETURNING id
                """,
                body.campaign_id,
                node.node_type,
                node.position_x,
                node.position_y,
                json.dumps(node.data),
            )
        new_id = str(row["id"])
        posted_ids.add(new_id)
        if node.id:
            node_id_map[node.id] = new_id

    # Edges are FK-free downstream; safe to wipe+reinsert. Do this BEFORE
    # deleting orphaned nodes so we don't trip the FK on sequence_edges.
    await execute("DELETE FROM sequence_edges WHERE campaign_id=$1", body.campaign_id)

    # Drop nodes the operator removed from the canvas. If a removed node
    # still has queue rows pointing at it, we can't delete it — null the
    # queue ref instead (the task is effectively orphaned and will be
    # skipped by the dispatcher next run).
    existing = await fetch_all(
        "SELECT id FROM sequence_nodes WHERE campaign_id=$1", body.campaign_id
    )
    stale = [str(r["id"]) for r in existing if str(r["id"]) not in posted_ids]
    if stale:
        await execute(
            "UPDATE queue SET node_id = NULL WHERE node_id = ANY($1::uuid[])",
            stale,
        )
        await execute(
            "DELETE FROM sequence_nodes WHERE id = ANY($1::uuid[])",
            stale,
        )

    # Insert Edges
    for edge in body.edges:
        # Use the mapped IDs if they exist, otherwise assume the IDs provided are UUIDs
        source_id = node_id_map.get(edge.source_node_id, edge.source_node_id)
        target_id = node_id_map.get(edge.target_node_id, edge.target_node_id)

        await execute(
            """
            INSERT INTO sequence_edges (campaign_id, source_node_id, target_node_id, source_handle, target_handle)
            VALUES ($1, $2, $3, $4, $5)
            """,
            body.campaign_id,
            source_id,
            target_id,
            edge.source_handle,
            edge.target_handle,
        )

    return {"status": "success"}


@router.get("/{campaign_id}/telemetry")
async def get_telemetry(campaign_id: str, user_id: str = Depends(get_current_user)):
    """Returns live edge activity and backpressure for the canvas overlay."""
    activity_rows = await fetch_all(
        """
        SELECT node_id::text, COUNT(*) AS cnt
        FROM queue
        WHERE campaign_id = $1
          AND status = 'sent'
          AND sent_at >= NOW() - INTERVAL '60 seconds'
        GROUP BY node_id
        """,
        campaign_id,
    )
    backpressure_rows = await fetch_all(
        """
        SELECT node_id::text, COUNT(*) AS cnt
        FROM queue
        WHERE campaign_id = $1
          AND status IN ('queued', 'locked')
        GROUP BY node_id
        """,
        campaign_id,
    )
    # Source breakdown — leads injected in the last 60 seconds, grouped by source.
    # This lives on the trigger_start node on the frontend.
    source_rows = await fetch_all(
        """
        SELECT COALESCE(source, 'unknown') AS source, COUNT(*) AS cnt
        FROM leads
        WHERE campaign_id = $1 AND created_at >= NOW() - INTERVAL '60 seconds'
        GROUP BY source
        """,
        campaign_id,
    )
    return {
        "activity": {r["node_id"]: r["cnt"] for r in activity_rows},
        "backpressure": {r["node_id"]: r["cnt"] for r in backpressure_rows},
        "sources_recent": {r["source"]: r["cnt"] for r in source_rows},
    }


@router.delete("/{campaign_id}")
async def clear_graph(campaign_id: str, user_id: str = Depends(get_current_user)):
    await execute("DELETE FROM sequence_nodes WHERE campaign_id=$1", campaign_id)
    return {"status": "deleted"}
