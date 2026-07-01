"""API-key management (N8N-001 Part 1c).

JWT-authed CRUD for a workspace's public API keys. A logged-in user mints keys
for their workspace; the raw key is returned ONCE at creation and only its
sha256 hash + display prefix are stored. Revoking sets ``revoked_at`` (soft —
the row is kept so ``last_used_at`` history survives and the key can never be
re-minted to the same value).

The keys these routes manage authenticate the ``/public/v1/*`` surface and the
webhook-subscription CRUD via ``app.auth_apikey.get_workspace_any``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.auth_apikey import generate_api_key
from app.db import execute, fetch_all, fetch_one

router = APIRouter()


class ApiKeyCreate(BaseModel):
    name: str = Field("", max_length=200, description="A human label so keys are tellable apart")


class ApiKeyCreated(BaseModel):
    id: uuid.UUID
    name: str
    key: str = Field(description="The RAW key — shown ONCE, never retrievable again")
    key_prefix: str
    created_at: datetime


class ApiKeyOut(BaseModel):
    id: uuid.UUID
    name: str
    key_prefix: str
    last_used_at: datetime | None
    revoked_at: datetime | None
    created_at: datetime


@router.post(
    "",
    response_model=ApiKeyCreated,
    status_code=201,
    summary="Mint a new API key",
    description=(
        "Generates an `omni_sk_...` key for the current workspace. The raw key is "
        "returned in this response ONLY — it is stored as a sha256 hash and can "
        "never be shown again. Use it as `Authorization: Bearer <key>` or "
        "`X-API-Key: <key>` on the `/public/v1/*` API."
    ),
)
async def create_api_key(
    body: ApiKeyCreate, ctx: AuthContext = Depends(get_current_workspace)
) -> ApiKeyCreated:
    raw_key, key_prefix, key_hash = generate_api_key()
    row = await fetch_one(
        """
        INSERT INTO omni_api_keys (workspace_id, name, key_prefix, key_hash, created_by)
        VALUES ($1, $2, $3, $4, $5)
        RETURNING id, name, key_prefix, created_at
        """,
        ctx.workspace_id, body.name, key_prefix, key_hash, ctx.user_id or None,
    )
    return ApiKeyCreated(
        id=row["id"], name=row["name"], key=raw_key,
        key_prefix=row["key_prefix"], created_at=row["created_at"],
    )


@router.get(
    "",
    response_model=list[ApiKeyOut],
    summary="List this workspace's API keys",
    description="Returns key metadata (prefix, name, usage, revocation) — never the raw key.",
)
async def list_api_keys(_: AuthContext = Depends(get_current_workspace)) -> list[ApiKeyOut]:
    rows = await fetch_all(
        "SELECT id, name, key_prefix, last_used_at, revoked_at, created_at "
        "FROM omni_api_keys ORDER BY created_at DESC"
    )
    return [ApiKeyOut.model_validate(r) for r in rows]


@router.delete(
    "/{key_id}",
    status_code=204,
    summary="Revoke an API key",
    description="Soft-revoke: sets `revoked_at`. The key stops authenticating immediately.",
)
async def revoke_api_key(
    key_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)
) -> None:
    result = await execute(
        "UPDATE omni_api_keys SET revoked_at = NOW() WHERE id = $1 AND revoked_at IS NULL",
        key_id,
    )
    # asyncpg returns e.g. "UPDATE 1"/"UPDATE 0". A 0 means no such live key.
    if result.endswith(" 0"):
        # Distinguish "already revoked / not found" — either way there's nothing
        # to revoke. 404 keeps the surface honest without leaking existence.
        exists = await fetch_one("SELECT 1 FROM omni_api_keys WHERE id = $1", key_id)
        if not exists:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="API key not found")
