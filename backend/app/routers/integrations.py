"""Integrations CRUD — one shape for every external provider.

Every node that needs an external service (SMTP, Apollo, Anthropic,
Unipile, Slack, Twilio, MindStudio, ZenRows, …) consumes a row in the
``connections`` table. This router is the operator-facing surface: list
connections, add an API-key connection, view what's configured, revoke.

OAuth connections (Google, ProductHunt, LinkedIn) live in the dedicated
``oauth*`` routers because their flow is provider-specific. Once authorised,
they also land in ``connections``.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.db import execute, fetch_all, fetch_one
from app.services.encryption import encrypt

router = APIRouter()


class ConnectionCreate(BaseModel):
    provider: str = Field(min_length=1, max_length=60, description="One of: apollo, hunter, proxycurl, smtp, anthropic, openai, gemini, mindstudio, slack, twilio, …")
    name: str = Field(min_length=1, max_length=120, description="Operator-chosen label (unique within (workspace, provider))")
    credentials: dict[str, Any] = Field(description="Provider-specific credential bundle; stored encrypted at rest")
    metadata: dict[str, Any] = Field(default_factory=dict, description="Non-secret config (e.g. SMTP host/port, default From address)")


class ConnectionOut(BaseModel):
    id: uuid.UUID
    provider: str
    name: str
    metadata: dict[str, Any]
    connected_at: datetime
    last_refreshed_at: datetime | None


@router.get(
    "",
    response_model=list[ConnectionOut],
    summary="List integrations connected to this workspace",
    description="Returns the connection metadata only — credentials never leave the server.",
)
async def list_connections(
    _: AuthContext = Depends(get_current_workspace),
    provider: str | None = None,
) -> list[ConnectionOut]:
    if provider:
        rows = await fetch_all(
            "SELECT id, provider, name, metadata, connected_at, last_refreshed_at FROM connections WHERE provider = $1 ORDER BY connected_at DESC",
            provider,
        )
    else:
        rows = await fetch_all(
            "SELECT id, provider, name, metadata, connected_at, last_refreshed_at FROM connections ORDER BY connected_at DESC"
        )
    return [ConnectionOut.model_validate(r) for r in rows]


@router.post(
    "",
    response_model=ConnectionOut,
    status_code=201,
    summary="Connect an integration (API-key style)",
    description="Persists the credential bundle encrypted at rest. For OAuth providers, use the dedicated /oauth/* endpoints instead.",
)
async def create_connection(body: ConnectionCreate, ctx: AuthContext = Depends(get_current_workspace)) -> ConnectionOut:
    import json

    encrypted = encrypt(json.dumps(body.credentials, separators=(",", ":")))
    try:
        row = await fetch_one(
            """
            INSERT INTO connections (workspace_id, provider, name, credentials_encrypted, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING id, provider, name, metadata, connected_at, last_refreshed_at
            """,
            ctx.workspace_id,
            body.provider,
            body.name,
            encrypted,
            body.metadata,
        )
    except Exception as e:  # noqa: BLE001 — most likely uniqueness violation
        raise HTTPException(status_code=409, detail="connection with that (provider, name) already exists") from e
    return ConnectionOut.model_validate(row)


@router.delete("/{connection_id}", status_code=204, summary="Disconnect (delete) an integration")
async def delete_connection(connection_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)) -> None:
    await execute("DELETE FROM connections WHERE id = $1", connection_id)
