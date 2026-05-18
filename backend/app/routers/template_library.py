"""Reusable template library — CRUD for message templates across channels."""

import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import get_current_user
from app.db import execute, fetch_all, fetch_one

router = APIRouter()


class LibraryTemplateCreate(BaseModel):
    name: str
    channel: str = "email"
    category: str = "general"
    subject: str | None = None
    body: str


class LibraryTemplateUpdate(BaseModel):
    name: str | None = None
    channel: str | None = None
    category: str | None = None
    subject: str | None = None
    body: str | None = None


def _extract_variables(body: str) -> list[str]:
    """Extract {{variable_name}} placeholders from template body."""
    return list(set(re.findall(r"\{\{(\w+)\}\}", body)))


@router.get("")
async def list_library_templates(
    channel: str | None = None,
    category: str | None = None,
    search: str | None = None,
    user_id: str = Depends(get_current_user),
):
    conditions = ["(user_id=$1 OR is_public=TRUE)"]
    params: list = [user_id]
    idx = 2

    if channel:
        conditions.append(f"channel=${idx}")
        params.append(channel)
        idx += 1

    if category:
        conditions.append(f"category=${idx}")
        params.append(category)
        idx += 1

    if search:
        conditions.append(f"(name ILIKE ${idx} OR body ILIKE ${idx})")
        params.append(f"%{search}%")
        idx += 1

    where = " AND ".join(conditions)
    rows = await fetch_all(
        f"SELECT * FROM template_library WHERE {where} ORDER BY updated_at DESC",
        *params,
    )
    return rows


@router.get("/{template_id}")
async def get_library_template(
    template_id: str,
    user_id: str = Depends(get_current_user),
):
    row = await fetch_one(
        "SELECT * FROM template_library WHERE id=$1 AND (user_id=$2 OR is_public=TRUE)",
        template_id,
        user_id,
    )
    if not row:
        raise HTTPException(404, "Template not found")
    return row


@router.post("", status_code=201)
async def create_library_template(
    body: LibraryTemplateCreate,
    user_id: str = Depends(get_current_user),
):
    variables = _extract_variables(body.body)
    row = await fetch_one(
        """INSERT INTO template_library (user_id, name, channel, category, subject, body, variables)
           VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""",
        user_id,
        body.name,
        body.channel,
        body.category,
        body.subject,
        body.body,
        variables,
    )
    return row


@router.put("/{template_id}")
async def update_library_template(
    template_id: str,
    body: LibraryTemplateUpdate,
    user_id: str = Depends(get_current_user),
):
    existing = await fetch_one(
        "SELECT * FROM template_library WHERE id=$1 AND user_id=$2",
        template_id,
        user_id,
    )
    if not existing:
        raise HTTPException(404, "Template not found or unauthorized")

    name = body.name or existing["name"]
    channel = body.channel or existing["channel"]
    category = body.category or existing["category"]
    subject = body.subject if body.subject is not None else existing["subject"]
    template_body = body.body or existing["body"]
    variables = _extract_variables(template_body)

    row = await fetch_one(
        """UPDATE template_library
           SET name=$1, channel=$2, category=$3, subject=$4, body=$5, variables=$6, updated_at=NOW()
           WHERE id=$7 RETURNING *""",
        name,
        channel,
        category,
        subject,
        template_body,
        variables,
        template_id,
    )
    return row


@router.delete("/{template_id}")
async def delete_library_template(
    template_id: str,
    user_id: str = Depends(get_current_user),
):
    await execute(
        "DELETE FROM template_library WHERE id=$1 AND user_id=$2",
        template_id,
        user_id,
    )
    return {"ok": True}
