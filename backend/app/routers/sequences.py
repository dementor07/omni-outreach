import json
from typing import Literal, List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

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
    "condition_replied",
    "condition_linkedin_distance",
    "condition_tag_exists",
    "condition_ai_screen",
    "condition_lead_source",
    "event_invite_accepted",
    "event_email_opened",
    "event_link_clicked",
    "delay",
    "split",
    "end",
]

class NodeCreate(BaseModel):
    id: str | None = None # React Flow ID
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
    nodes: List[NodeCreate]
    edges: List[EdgeCreate]

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

    # Transactional update: Delete old nodes/edges and insert new ones
    # In a real production app, we'd use a transaction here. 
    # For now, we'll execute sequentially.
    
    await execute("DELETE FROM sequence_edges WHERE campaign_id=$1", body.campaign_id)
    await execute("DELETE FROM sequence_nodes WHERE campaign_id=$1", body.campaign_id)

    # Insert Nodes
    node_id_map = {} # Map temporary React Flow IDs to actual DB IDs if needed
    for node in body.nodes:
        inserted = await fetch_one(
            """
            INSERT INTO sequence_nodes (campaign_id, node_type, position_x, position_y, data)
            VALUES ($1, $2, $3, $4, $5)
            RETURNING id
            """,
            body.campaign_id, node.node_type, node.position_x, node.position_y, json.dumps(node.data)
        )
        if node.id:
            node_id_map[node.id] = inserted["id"]

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
            body.campaign_id, source_id, target_id, edge.source_handle, edge.target_handle
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
    return {
        "activity": {r["node_id"]: r["cnt"] for r in activity_rows},
        "backpressure": {r["node_id"]: r["cnt"] for r in backpressure_rows},
    }


@router.delete("/{campaign_id}")
async def clear_graph(campaign_id: str, user_id: str = Depends(get_current_user)):
    await execute("DELETE FROM sequence_nodes WHERE campaign_id=$1", campaign_id)
    return {"status": "deleted"}
