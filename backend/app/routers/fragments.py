"""Sub-graph fragments.

Operator saves a cluster of canvas nodes + edges as a named fragment. Drop
the fragment back into any campaign and the original nodes are inlined with
fresh UUIDs (preserving relative positions and internal edges).

The fragment library is per-user. No live link back to existing campaigns —
edits to a fragment after drop don't propagate; that's by design (canvas is
mutable, fragments are starter scaffolds).
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

router = APIRouter()
log = logging.getLogger(__name__)


class FragmentNode(BaseModel):
    id: str
    node_type: str
    position_x: float
    position_y: float
    data: dict = {}


class FragmentEdge(BaseModel):
    source_node_id: str
    target_node_id: str
    source_handle: str = "default"
    target_handle: str = "default"


class FragmentCreate(BaseModel):
    name: str
    description: str | None = None
    nodes: list[FragmentNode]
    edges: list[FragmentEdge]


class FragmentInstantiate(BaseModel):
    campaign_id: str
    offset_x: float = 0
    offset_y: float = 0


@router.get("")
async def list_fragments(user_id: str = Depends(get_current_user)):
    rows = await fetch_all(
        "SELECT id, name, description, jsonb_array_length(nodes) AS node_count, "
        "created_at, updated_at FROM sequence_fragments "
        "WHERE user_id IS NULL OR user_id=$1 ORDER BY updated_at DESC LIMIT 100",
        user_id,
    )
    return {"fragments": rows}


@router.post("", status_code=201)
async def create_fragment(body: FragmentCreate, user_id: str = Depends(get_current_user)):
    row = await fetch_one(
        """
        INSERT INTO sequence_fragments (user_id, name, description, nodes, edges)
        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb)
        RETURNING id
        """,
        user_id,
        body.name.strip(),
        (body.description or "").strip() or None,
        json.dumps([n.model_dump() for n in body.nodes]),
        json.dumps([e.model_dump() for e in body.edges]),
    )
    return {"id": str(row["id"])}


@router.delete("/{fragment_id}", status_code=204)
async def delete_fragment(fragment_id: str, user_id: str = Depends(get_current_user)):
    await execute(
        "DELETE FROM sequence_fragments WHERE id=$1 AND (user_id IS NULL OR user_id=$2)",
        fragment_id, user_id,
    )


@router.post("/{fragment_id}/instantiate")
async def instantiate(fragment_id: str, body: FragmentInstantiate, user_id: str = Depends(get_current_user)):
    """Materialize a fragment into a target campaign. Returns the new node UUIDs
    so the frontend can refresh its canvas state."""
    row = await fetch_one(
        "SELECT nodes, edges FROM sequence_fragments WHERE id=$1 AND (user_id IS NULL OR user_id=$2)",
        fragment_id, user_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="Fragment not found")

    campaign = await fetch_one("SELECT id FROM campaigns WHERE id=$1", body.campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")

    raw_nodes = row["nodes"] if isinstance(row["nodes"], list) else json.loads(row["nodes"])
    raw_edges = row["edges"] if isinstance(row["edges"], list) else json.loads(row["edges"])

    # Remap node IDs to fresh UUIDs so we can drop the fragment multiple times.
    id_map: dict[str, str] = {n["id"]: str(uuid.uuid4()) for n in raw_nodes}

    created: list[dict] = []
    for n in raw_nodes:
        new_id = id_map[n["id"]]
        await execute(
            """
            INSERT INTO sequence_nodes (id, campaign_id, node_type, position_x, position_y, data)
            VALUES ($1, $2, $3, $4, $5, $6::jsonb)
            """,
            new_id,
            body.campaign_id,
            n["node_type"],
            float(n.get("position_x", 0)) + body.offset_x,
            float(n.get("position_y", 0)) + body.offset_y,
            json.dumps(n.get("data") or {}),
        )
        created.append({"id": new_id, "node_type": n["node_type"]})

    for e in raw_edges:
        src = id_map.get(e["source_node_id"], e["source_node_id"])
        tgt = id_map.get(e["target_node_id"], e["target_node_id"])
        await execute(
            """
            INSERT INTO sequence_edges (campaign_id, source_node_id, target_node_id, source_handle, target_handle)
            VALUES ($1, $2, $3, $4, $5)
            """,
            body.campaign_id, src, tgt,
            e.get("source_handle", "default"),
            e.get("target_handle", "default"),
        )

    return {"created_nodes": created}
