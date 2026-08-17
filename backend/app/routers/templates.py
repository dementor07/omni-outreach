"""B5 — message template library CRUD.

A workspace-shared library of reusable message copy. Each template has a name,
a channel, an optional category + subject (email), and a body that supports the
same ``{{variable}}`` placeholders the channel payload renderer understands.
Operators manage these on the Templates page; campaign authors copy a template
body onto a channel / ai.compose node.

Workspace-scoped + RLS (migration 033). Mirrors the suppression CRUD shape.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

import asyncpg
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import execute, fetch_all, fetch_one

router = APIRouter()

TemplateChannel = Literal["email", "linkedin", "sms", "whatsapp", "instagram", "telegram", "voice"]


class TemplateCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    channel: TemplateChannel = "email"
    category: str | None = Field(default=None, max_length=80)
    subject: str | None = Field(default=None, max_length=300)
    body: str = Field(min_length=1, max_length=20000)


class TemplateUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    channel: TemplateChannel | None = None
    category: str | None = Field(default=None, max_length=80)
    subject: str | None = Field(default=None, max_length=300)
    body: str | None = Field(default=None, min_length=1, max_length=20000)


class TemplateOut(BaseModel):
    id: uuid.UUID
    name: str
    channel: str
    category: str | None
    subject: str | None
    body: str
    created_at: datetime
    updated_at: datetime


_SELECT = "SELECT id, name, channel, category, subject, body, created_at, updated_at FROM omni_templates"


@router.get("", response_model=list[TemplateOut], summary="List message templates")
async def list_templates(_: AuthContext = Depends(get_current_workspace)) -> list[TemplateOut]:
    rows = await fetch_all(f"{_SELECT} ORDER BY updated_at DESC")
    return [TemplateOut.model_validate(r) for r in rows]


@router.post("", response_model=TemplateOut, status_code=201, summary="Create a template")
async def create_template(
    body: TemplateCreate, ctx: AuthContext = Depends(get_current_workspace)
) -> TemplateOut:
    try:
        row = await fetch_one(
            """
            INSERT INTO omni_templates (workspace_id, name, channel, category, subject, body, created_by)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            RETURNING id, name, channel, category, subject, body, created_at, updated_at
            """,
            ctx.workspace_id,
            body.name.strip(),
            body.channel,
            body.category,
            body.subject,
            body.body,
            ctx.user_id,
        )
    except asyncpg.UniqueViolationError as e:
        raise HTTPException(status_code=409, detail="a template with that name already exists") from e
    return TemplateOut.model_validate(row)


@router.patch("/{template_id}", response_model=TemplateOut, summary="Update a template")
async def update_template(
    template_id: uuid.UUID,
    body: TemplateUpdate,
    _: AuthContext = Depends(get_current_workspace),
) -> TemplateOut:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status_code=400, detail="no fields to update")
    if "name" in fields and fields["name"]:
        fields["name"] = fields["name"].strip()
    # Build a parameterised SET clause from the supplied fields only.
    cols = list(fields.keys())
    assignments = ", ".join(f"{c} = ${i + 1}" for i, c in enumerate(cols))
    values = [fields[c] for c in cols]
    try:
        row = await fetch_one(
            f"UPDATE omni_templates SET {assignments}, updated_at = NOW() "
            f"WHERE id = ${len(cols) + 1} "
            "RETURNING id, name, channel, category, subject, body, created_at, updated_at",
            *values,
            template_id,
        )
    except asyncpg.UniqueViolationError as e:
        raise HTTPException(status_code=409, detail="a template with that name already exists") from e
    if not row:
        raise HTTPException(status_code=404, detail="template not found")
    return TemplateOut.model_validate(row)


@router.delete("/{template_id}", status_code=204, summary="Delete a template")
async def delete_template(template_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)) -> None:
    await execute("DELETE FROM omni_templates WHERE id = $1", template_id)
