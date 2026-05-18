from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import fetch_all, fetch_one

router = APIRouter()


class TemplateUpsert(BaseModel):
    node_id: str
    subject: str | None = None
    body: str


@router.get("")
async def get_template(node_id: str, user_id: str = Depends(get_current_user)):
    rows = await fetch_all(
        "SELECT * FROM templates WHERE node_id=$1 ORDER BY created_at DESC LIMIT 1",
        node_id,
    )
    return rows[0] if rows else None


@router.post("", status_code=201)
async def upsert_template(body: TemplateUpsert, user_id: str = Depends(get_current_user)):
    node = await fetch_one("SELECT campaign_id, node_type FROM sequence_nodes WHERE id=$1", body.node_id)
    if not node:
        raise HTTPException(status_code=404, detail="Sequence node not found")

    existing = await fetch_one("SELECT id FROM templates WHERE node_id=$1 LIMIT 1", body.node_id)

    if existing:
        return await fetch_one(
            "UPDATE templates SET subject=$1, body=$2 WHERE id=$3 RETURNING *",
            body.subject,
            body.body,
            existing["id"],
        )

    channel = node["node_type"].replace("action_", "")
    name = f"{channel} template"
    return await fetch_one(
        """
        INSERT INTO templates (campaign_id, node_id, name, channel, subject, body)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING *
        """,
        node["campaign_id"],
        body.node_id,
        name,
        channel,
        body.subject,
        body.body,
    )
