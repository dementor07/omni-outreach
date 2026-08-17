"""TONE-PRESET-001 — message tone preset library.

A read surface over ``omni_message_tones`` (migration 049): the 12 built-in
tone presets the team authored (global, workspace_id NULL) plus any
workspace-custom tones. Campaign authors pick a ``tone_id`` on an ai.compose
step; the dispatcher resolves the full preset into the compose prompt.

v1 is read-only (the builtins are managed by the seed migration). A future
iteration can add workspace-custom CRUD here mirroring the templates router.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth import AuthContext, get_current_workspace
from app.db import fetch_all, fetch_one

router = APIRouter()


class ToneOut(BaseModel):
    tone_id: int
    tone: str
    description: str
    spec: dict[str, Any]
    is_builtin: bool


def _row_to_out(row: dict) -> ToneOut:
    spec = row.get("spec")
    if isinstance(spec, str):
        import json

        spec = json.loads(spec)
    return ToneOut(
        tone_id=row["tone_id"],
        tone=row["tone"],
        description=row.get("description") or "",
        spec=spec or {},
        is_builtin=bool(row.get("is_builtin")),
    )


@router.get(
    "",
    response_model=list[ToneOut],
    summary="List message tone presets",
    description=(
        "The tone library for AI compose — the built-in presets (global) and any "
        "workspace-custom tones, ordered by tone_id. A workspace-custom tone with "
        "the same tone_id as a builtin shadows it."
    ),
)
async def list_tones(_: AuthContext = Depends(get_current_workspace)) -> list[ToneOut]:
    # RLS already scopes visibility (global builtins + this workspace's customs).
    # DISTINCT ON keeps the workspace-custom row over the global builtin per tone_id.
    rows = await fetch_all(
        "SELECT DISTINCT ON (tone_id) tone_id, tone, description, spec, is_builtin "
        "FROM omni_message_tones "
        "ORDER BY tone_id, workspace_id NULLS LAST"
    )
    return [_row_to_out(dict(r)) for r in rows]


@router.get("/{tone_id}", response_model=ToneOut, summary="Fetch one tone preset")
async def get_tone(tone_id: int, _: AuthContext = Depends(get_current_workspace)) -> ToneOut:
    row = await fetch_one(
        "SELECT tone_id, tone, description, spec, is_builtin FROM omni_message_tones "
        "WHERE tone_id=$1 ORDER BY workspace_id NULLS LAST LIMIT 1",
        tone_id,
    )
    if not row:
        raise HTTPException(status_code=404, detail="tone not found")
    return _row_to_out(dict(row))
