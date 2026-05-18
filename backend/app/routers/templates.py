from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

router = APIRouter()


class TemplateUpsert(BaseModel):
    node_id: str
    subject: str | None = None
    body: str


class SharedTemplateCreate(BaseModel):
    name: str
    channel: str
    subject: str | None = None
    body: str
    description: str | None = None


class SharedTemplateUpdate(BaseModel):
    name: str | None = None
    subject: str | None = None
    body: str | None = None
    description: str | None = None


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


# --- Shared (linked) templates ---------------------------------------------

@router.get("/shared")
async def list_shared_templates(_user_id: str = Depends(get_current_user)):
    """Library of shared templates that can be linked from any sequence node."""
    rows = await fetch_all(
        "SELECT id, name, channel, subject, body, description, created_at "
        "FROM templates WHERE is_shared = TRUE ORDER BY name ASC"
    )
    return {"templates": rows}


@router.post("/shared", status_code=201)
async def create_shared_template(body: SharedTemplateCreate, _user_id: str = Depends(get_current_user)):
    # Shared templates are not owned by a campaign; we still satisfy the
    # campaign_id NOT NULL constraint by parking them under the first
    # campaign the user has access to. Acceptable until we drop the FK.
    campaign = await fetch_one("SELECT id FROM campaigns ORDER BY created_at ASC LIMIT 1")
    if not campaign:
        raise HTTPException(status_code=400, detail="No campaigns exist yet — create one first.")
    row = await fetch_one(
        """
        INSERT INTO templates (campaign_id, node_id, name, channel, subject, body, description, is_shared)
        VALUES ($1, NULL, $2, $3, $4, $5, $6, TRUE)
        RETURNING id, name, channel, subject, body, description, created_at
        """,
        campaign["id"], body.name.strip(), body.channel.strip(),
        body.subject, body.body, body.description,
    )
    return row


@router.patch("/shared/{template_id}")
async def update_shared_template(template_id: str, body: SharedTemplateUpdate, _user_id: str = Depends(get_current_user)):
    existing = await fetch_one("SELECT id FROM templates WHERE id=$1 AND is_shared=TRUE", template_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Shared template not found")
    sets: list[str] = []
    args: list = []
    for field, val in [("name", body.name), ("subject", body.subject), ("body", body.body), ("description", body.description)]:
        if val is not None:
            args.append(val)
            sets.append(f"{field}=${len(args)}")
    if not sets:
        return await fetch_one("SELECT * FROM templates WHERE id=$1", template_id)
    args.append(template_id)
    return await fetch_one(
        f"UPDATE templates SET {', '.join(sets)} WHERE id=${len(args)} RETURNING *",
        *args,
    )


@router.delete("/shared/{template_id}", status_code=204)
async def delete_shared_template(template_id: str, _user_id: str = Depends(get_current_user)):
    await execute("DELETE FROM templates WHERE id=$1 AND is_shared=TRUE", template_id)


@router.get("/by-id/{template_id}")
async def get_template_by_id(template_id: str, _user_id: str = Depends(get_current_user)):
    """Resolve a template by its UUID (used when a sequence_node carries
    data.template_id to reference a shared template)."""
    row = await fetch_one("SELECT * FROM templates WHERE id=$1", template_id)
    if not row:
        raise HTTPException(status_code=404, detail="Template not found")
    return row
