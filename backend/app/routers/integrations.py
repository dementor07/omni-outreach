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

import logging
import uuid
from datetime import datetime
from typing import Any

import asyncpg
import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.config import settings
from app.db import execute, fetch_all, fetch_one
from app.services.encryption import decrypt, encrypt

logger = logging.getLogger(__name__)
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
            "SELECT id, provider, name, metadata, connected_at, last_refreshed_at FROM omni_connections WHERE provider = $1 ORDER BY connected_at DESC",
            provider,
        )
    else:
        rows = await fetch_all(
            "SELECT id, provider, name, metadata, connected_at, last_refreshed_at FROM omni_connections ORDER BY connected_at DESC"
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
            INSERT INTO omni_connections (workspace_id, provider, name, credentials_encrypted, metadata)
            VALUES ($1, $2, $3, $4, $5::jsonb)
            RETURNING id, provider, name, metadata, connected_at, last_refreshed_at
            """,
            ctx.workspace_id,
            body.provider,
            body.name,
            encrypted,
            body.metadata,
        )
    except asyncpg.UniqueViolationError as e:
        # INT-001: only a real uniqueness collision is a 409. Other DB errors
        # (connection lost, constraint/type errors) must surface as 500, not be
        # masked as "already exists".
        raise HTTPException(status_code=409, detail="connection with that (provider, name) already exists") from e
    return ConnectionOut.model_validate(row)


@router.delete("/{connection_id}", status_code=204, summary="Disconnect (delete) an integration")
async def delete_connection(connection_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)) -> None:
    await execute("DELETE FROM omni_connections WHERE id = $1", connection_id)


# ── Sending Accounts ─────────────────────────────────────────────────────────

class SendingAccountOut(BaseModel):
    id: uuid.UUID
    connection_id: uuid.UUID
    provider: str
    channel_kind: str
    external_identity: str
    display_name: str | None
    daily_cap: int
    hourly_cap: int
    sends_today: int
    sends_this_hour: int
    status: str
    warmup_target: int | None
    last_used_at: datetime | None
    health: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class SendingAccountCreate(BaseModel):
    channel_kind: str = Field(..., description="email|linkedin|sms|voice|whatsapp|instagram|telegram")
    external_identity: str = Field(min_length=1, max_length=255)
    display_name: str | None = None
    daily_cap: int = Field(default=0, ge=0)
    hourly_cap: int = Field(default=0, ge=0)
    warmup_target: int | None = Field(default=None, ge=0)
    status: str = Field(default="active")


class SendingAccountUpdate(BaseModel):
    display_name: str | None = None
    daily_cap: int | None = Field(default=None, ge=0)
    hourly_cap: int | None = Field(default=None, ge=0)
    warmup_target: int | None = Field(default=None, ge=0)
    status: str | None = None


class SyncResult(BaseModel):
    synced: int
    accounts: list[SendingAccountOut]


def _linkedin_safe_cap(channel_kind: str, daily_cap: int) -> int:
    if channel_kind == "linkedin" and daily_cap == 0:
        return 20
    return daily_cap


def _unipile_seat_status(item: dict) -> str:
    """UNIPILE-HEALTH-001: map a Unipile account's reported health to our seat
    status, so an unhealthy seat is NOT synced 'active' and selectable for sending
    (it would just fail at send time). Unipile reports per-account health under
    sources[].status (or a top-level status); OK/CONNECTED → active, anything else
    (CREDENTIALS = needs re-auth, ERROR, DISCONNECTED, …) → paused. The send-account
    selector only picks active/warming seats, so a paused seat is skipped."""
    sources = item.get("sources") or []
    raw = ""
    if sources and isinstance(sources, list) and isinstance(sources[0], dict):
        raw = str(sources[0].get("status") or "")
    raw = (raw or str(item.get("status") or "")).strip().upper()
    return "active" if raw in ("OK", "CONNECTED", "ACTIVE", "") else "paused"


@router.get("/accounts", response_model=list[SendingAccountOut], summary="List all accounts across all connections")
async def list_all_accounts(ctx: AuthContext = Depends(get_current_workspace)) -> list[SendingAccountOut]:
    rows = await fetch_all(
        "SELECT * FROM omni_sending_accounts WHERE workspace_id = $1 ORDER BY created_at DESC",
        ctx.workspace_id,
    )
    return [SendingAccountOut.model_validate(r) for r in rows]


@router.get("/{connection_id}/accounts", response_model=list[SendingAccountOut], summary="List accounts under one connection")
async def list_accounts(connection_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)) -> list[SendingAccountOut]:
    rows = await fetch_all(
        "SELECT * FROM omni_sending_accounts WHERE connection_id = $1 ORDER BY created_at DESC",
        connection_id,
    )
    return [SendingAccountOut.model_validate(r) for r in rows]


@router.post("/{connection_id}/accounts", response_model=SendingAccountOut, status_code=201, summary="Manual add account")
async def create_account(connection_id: uuid.UUID, body: SendingAccountCreate, ctx: AuthContext = Depends(get_current_workspace)) -> SendingAccountOut:
    conn_row = await fetch_one("SELECT provider FROM omni_connections WHERE id = $1", connection_id)
    if not conn_row:
        raise HTTPException(status_code=404, detail="connection not found")

    provider = conn_row["provider"]
    daily_cap = _linkedin_safe_cap(body.channel_kind, body.daily_cap)

    try:
        row = await fetch_one(
            """
            INSERT INTO omni_sending_accounts (workspace_id, connection_id, provider, channel_kind, external_identity, display_name, daily_cap, hourly_cap, warmup_target, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
            RETURNING *
            """,
            ctx.workspace_id,
            connection_id,
            provider,
            body.channel_kind,
            body.external_identity,
            body.display_name,
            daily_cap,
            body.hourly_cap,
            body.warmup_target,
            body.status,
        )
    except asyncpg.UniqueViolationError as e:
        raise HTTPException(status_code=409, detail="account already exists for this connection") from e
    return SendingAccountOut.model_validate(row)


@router.patch("/accounts/{account_id}", response_model=SendingAccountOut, summary="Edit account")
async def update_account(account_id: uuid.UUID, body: SendingAccountUpdate, _: AuthContext = Depends(get_current_workspace)) -> SendingAccountOut:
    fields = body.model_dump(exclude_none=True)
    if not fields:
        row = await fetch_one("SELECT * FROM omni_sending_accounts WHERE id = $1", account_id)
        if not row:
            raise HTTPException(status_code=404, detail="account not found")
        return SendingAccountOut.model_validate(row)

    set_sql = ", ".join(f"{k} = ${i + 2}" for i, k in enumerate(fields))
    row = await fetch_one(
        f"UPDATE omni_sending_accounts SET {set_sql}, updated_at = NOW() WHERE id = $1 RETURNING *",
        account_id,
        *fields.values()
    )
    if not row:
        raise HTTPException(status_code=404, detail="account not found")
    return SendingAccountOut.model_validate(row)


@router.delete("/accounts/{account_id}", status_code=204, summary="Remove account")
async def delete_account(account_id: uuid.UUID, _: AuthContext = Depends(get_current_workspace)) -> None:
    await execute("DELETE FROM omni_sending_accounts WHERE id = $1", account_id)


@router.post("/{connection_id}/accounts/sync", response_model=SyncResult, summary="Sync Unipile accounts")
async def sync_accounts(connection_id: uuid.UUID, ctx: AuthContext = Depends(get_current_workspace)) -> SyncResult:
    import json

    conn_row = await fetch_one("SELECT provider, credentials_encrypted, metadata FROM omni_connections WHERE id = $1", connection_id)
    if not conn_row:
        raise HTTPException(status_code=404, detail="connection not found")

    provider = conn_row["provider"]
    if provider != "unipile":
        rows = await fetch_all("SELECT * FROM omni_sending_accounts WHERE connection_id = $1 ORDER BY created_at DESC", connection_id)
        return SyncResult(synced=0, accounts=[SendingAccountOut.model_validate(r) for r in rows])

    creds = json.loads(decrypt(conn_row["credentials_encrypted"]))
    api_key = creds.get("api_key")
    base_url = creds.get("base_url")
    if not api_key or not base_url:
        raise HTTPException(status_code=502, detail="unipile sync failed: invalid credentials")

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base_url.rstrip('/')}/api/v1/accounts", headers={"X-API-KEY": api_key})
            resp.raise_for_status()
            unipile_accounts = resp.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"unipile sync failed: {str(e)}")

    synced = 0
    items = unipile_accounts if isinstance(unipile_accounts, list) else unipile_accounts.get("items", [])

    for item in items:
        ext_id = item["id"]
        name = item.get("name")
        p_type = str(item.get("provider", item.get("type", ""))).upper()
        if p_type == "LINKEDIN":
            channel_kind = "linkedin"
        elif p_type == "WHATSAPP":
            channel_kind = "whatsapp"
        elif p_type in ("MESSENGER", "INSTAGRAM"):
            channel_kind = "instagram"
        else:
            channel_kind = "linkedin"

        daily_cap = _linkedin_safe_cap(channel_kind, 0)
        seat_status = _unipile_seat_status(item)

        await execute(
            """
            INSERT INTO omni_sending_accounts (workspace_id, connection_id, provider, channel_kind, external_identity, display_name, daily_cap, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (workspace_id, connection_id, external_identity)
            DO UPDATE SET display_name = EXCLUDED.display_name, status = EXCLUDED.status, updated_at = NOW()
            """,
            ctx.workspace_id,
            connection_id,
            provider,
            channel_kind,
            ext_id,
            name,
            daily_cap,
            seat_status,
        )
        synced += 1

    # UNIPILE-FULL: auto-register omni's inbound URL as a native Unipile webhook
    # (message_received + account_status) so we stop relying only on polling.
    # Best-effort + idempotent: skip if a webhook id is already recorded on the
    # connection metadata; a failure here must not fail the seat sync.
    await _ensure_unipile_webhook(ctx, connection_id, conn_row.get("metadata"), api_key, base_url)

    rows = await fetch_all("SELECT * FROM omni_sending_accounts WHERE connection_id = $1 ORDER BY created_at DESC", connection_id)
    return SyncResult(synced=synced, accounts=[SendingAccountOut.model_validate(r) for r in rows])


async def _ensure_unipile_webhook(
    ctx: AuthContext, connection_id, metadata, api_key: str, base_url: str
) -> None:
    """Register omni's inbound URL as a Unipile native webhook, once per connection.

    Stores the returned webhook id in the connection's metadata.unipile_webhook_id
    so a re-sync doesn't duplicate it (and a later DELETE can find it). Fully
    best-effort — never raises into the sync path."""
    import json as _json

    meta = metadata
    if isinstance(meta, str):
        try:
            meta = _json.loads(meta)
        except _json.JSONDecodeError:
            meta = {}
    meta = meta or {}
    if meta.get("unipile_webhook_id"):
        return  # already registered

    inbound_url = f"{settings.get_public_base_url()}/api/webhooks/unipile/{ctx.workspace_id}"
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                f"{base_url.rstrip('/')}/api/v1/webhooks",
                headers={"X-API-KEY": api_key, "content-type": "application/json"},
                json={
                    "request_url": inbound_url,
                    "source": "messaging",
                    "events": ["message_received", "account_status"],
                    "name": "omni-inbound",
                },
            )
        if resp.status_code >= 400:
            logger.warning("[unipile] webhook auto-register HTTP %s: %s", resp.status_code, resp.text[:200])
            return
        body = resp.json() if resp.content else {}
        webhook_id = body.get("webhook_id") or body.get("id")
        if not webhook_id:
            return
        new_meta = {**meta, "unipile_webhook_id": str(webhook_id)}
        await execute(
            "UPDATE omni_connections SET metadata = $1 WHERE id = $2",
            _json.dumps(new_meta), connection_id,
        )
        logger.info("[unipile] registered native webhook %s for connection %s", webhook_id, connection_id)
    except Exception:  # noqa: BLE001 — never fail the sync over webhook registration
        logger.exception("[unipile] webhook auto-register failed for connection %s", connection_id)
