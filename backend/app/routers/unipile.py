"""Unipile control-plane router (UNIPILE-FULL group C/D).

JWT-authed endpoints the frontend calls for workspace-level Unipile reads/CRUD:
account health/lifecycle, inbox reads (chats/messages), inmail-balance, and
native webhook registration/list/delete. These are synchronous Unipile API reads
made directly by the control plane (app.services.unipile_client) — NOT routed
through Kafka/the muscle (that path is per-lead only).

The Unipile key lives in the workspace's connection bundle and is resolved inside
the client under system_scope(); it never appears in a request/response body.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.config import settings
from app.services.unipile_client import UnipileClient, UnipileError, UnipileNotConfigured

router = APIRouter()


async def _client(ctx: AuthContext) -> UnipileClient:
    try:
        return await UnipileClient.for_workspace(str(ctx.workspace_id))
    except UnipileNotConfigured as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


# ── Accounts (health / lifecycle) ──────────────────────────────────────────────
@router.get("/accounts", summary="List Unipile accounts (seats) with health")
async def list_accounts(ctx: AuthContext = Depends(get_current_workspace)):
    client = await _client(ctx)
    try:
        return await client.list_accounts()
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/accounts/{account_id}", summary="Fetch one account's status")
async def get_account(account_id: str, ctx: AuthContext = Depends(get_current_workspace)):
    client = await _client(ctx)
    try:
        return await client.get_account(account_id)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/accounts/{account_id}/resync", summary="Trigger an account resync")
async def resync_account(account_id: str, ctx: AuthContext = Depends(get_current_workspace)):
    client = await _client(ctx)
    try:
        return await client.resync_account(account_id)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/accounts/{account_id}/reconnect", summary="Reconnect a disconnected account")
async def reconnect_account(account_id: str, ctx: AuthContext = Depends(get_current_workspace)):
    client = await _client(ctx)
    try:
        return await client.reconnect_account(account_id)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/accounts/{account_id}/restart", summary="Restart an account")
async def restart_account(account_id: str, ctx: AuthContext = Depends(get_current_workspace)):
    client = await _client(ctx)
    try:
        return await client.restart_account(account_id)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# ── LinkedIn reads ──────────────────────────────────────────────────────────────
@router.get("/inmail-balance", summary="Remaining InMail credits for a seat")
async def inmail_balance(
    account_id: str = Query(..., description="Unipile account id (seat)"),
    ctx: AuthContext = Depends(get_current_workspace),
):
    client = await _client(ctx)
    try:
        return await client.inmail_balance(account_id)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/company/{company_id}", summary="LinkedIn company profile (enrichment)")
async def company_profile(
    company_id: str,
    account_id: str = Query(..., description="Unipile account id (seat)"),
    ctx: AuthContext = Depends(get_current_workspace),
):
    client = await _client(ctx)
    try:
        return await client.company_profile(account_id, company_id)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# ── Inbox reads ─────────────────────────────────────────────────────────────────
@router.get("/chats", summary="List chats for a seat (Inbox)")
async def list_chats(
    account_id: str = Query(...),
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_workspace),
):
    client = await _client(ctx)
    try:
        return await client.list_chats(account_id, cursor=cursor, limit=limit)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/chats/{chat_id}/messages", summary="List messages in a chat")
async def list_chat_messages(
    chat_id: str,
    cursor: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    ctx: AuthContext = Depends(get_current_workspace),
):
    client = await _client(ctx)
    try:
        return await client.list_chat_messages(chat_id, cursor=cursor, limit=limit)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.get("/chats/{chat_id}/attendees", summary="List a chat's attendees")
async def list_chat_attendees(chat_id: str, ctx: AuthContext = Depends(get_current_workspace)):
    client = await _client(ctx)
    try:
        return await client.list_chat_attendees(chat_id)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


# ── Native webhooks ─────────────────────────────────────────────────────────────
class WebhookRegister(BaseModel):
    events: list[str] = Field(
        default_factory=lambda: ["message_received", "account_status"],
        description="Unipile event names to subscribe this workspace's inbound URL to",
    )


@router.get("/webhooks", summary="List registered Unipile webhooks")
async def list_webhooks(ctx: AuthContext = Depends(get_current_workspace)):
    client = await _client(ctx)
    try:
        return await client.list_webhooks()
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.post("/webhooks", summary="Register omni's inbound URL as a Unipile webhook")
async def register_webhook(body: WebhookRegister, ctx: AuthContext = Depends(get_current_workspace)):
    client = await _client(ctx)
    # omni's public inbound endpoint (the Unipile consumer in webhooks_in.py:
    # POST /webhooks/unipile/{workspace_id}). The workspace id in the path is how
    # the consumer scopes the pushed event to this tenant.
    inbound_url = f"{settings.get_public_base_url()}/api/webhooks/unipile/{ctx.workspace_id}"
    try:
        return await client.register_webhook(inbound_url, body.events, name="omni-inbound")
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e


@router.delete("/webhooks/{webhook_id}", status_code=204, summary="Delete a Unipile webhook")
async def delete_webhook(webhook_id: str, ctx: AuthContext = Depends(get_current_workspace)):
    client = await _client(ctx)
    try:
        await client.delete_webhook(webhook_id)
    except UnipileError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
