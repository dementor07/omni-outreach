"""Suppression list (DNC) CRUD — the operator surface for the Blacklist page.

Rows here are ENFORCED at the outbound-send seam (transition_worker._fire_node
via services.suppression). Workspace-scoped + RLS; the unsubscribe inbox
classifier also writes here with source='unsubscribe'.
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

SuppressionKind = Literal["email", "domain", "phone", "linkedin"]


class SuppressionCreate(BaseModel):
    kind: SuppressionKind = Field(description="email | domain | phone | linkedin")
    value: str = Field(min_length=1, max_length=320, description="The address/domain/number/handle to suppress")
    reason: str | None = Field(default=None, max_length=200)


class SuppressionOut(BaseModel):
    id: uuid.UUID
    kind: str
    value: str
    reason: str | None
    source: str
    created_at: datetime


@router.get("", response_model=list[SuppressionOut], summary="List suppression (DNC) rules")
async def list_rules(_: AuthContext = Depends(get_current_workspace)) -> list[SuppressionOut]:
    rows = await fetch_all(
        "SELECT id, kind, value, reason, source, created_at "
        "FROM omni_suppression_list ORDER BY created_at DESC"
    )
    return [SuppressionOut.model_validate(r) for r in rows]


@router.post("", response_model=SuppressionOut, status_code=201, summary="Add a suppression rule")
async def create_rule(
    body: SuppressionCreate, ctx: AuthContext = Depends(get_current_workspace)
) -> SuppressionOut:
    value = body.value.strip().lower()
    try:
        row = await fetch_one(
            """
            INSERT INTO omni_suppression_list (workspace_id, kind, value, reason, source)
            VALUES ($1, $2, $3, $4, 'manual')
            RETURNING id, kind, value, reason, source, created_at
            """,
            ctx.workspace_id,
            body.kind,
            value,
            body.reason,
        )
    except asyncpg.UniqueViolationError as e:
        raise HTTPException(status_code=409, detail="that suppression rule already exists") from e
    return SuppressionOut.model_validate(row)


@router.delete("/{rule_id}", status_code=204, summary="Remove a suppression rule")
async def delete_rule(rule_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)) -> None:
    await execute("DELETE FROM omni_suppression_list WHERE id = $1", rule_id)
