"""Shared async Unipile client for CONTROL-PLANE reads/CRUD (UNIPILE-FULL group C/D).

The Rust muscle owns per-lead ACTIONS (it redeems a credential_ref). This client
is the OTHER half: workspace-level, synchronous Unipile reads + CRUD that the
control plane (Python) makes directly with httpx — account health, inbox reads,
inmail-balance, native webhook CRUD. These are NOT per-lead, so they don't ride
Kafka/the muscle.

Auth: the workspace's Unipile connection bundle (``omni_connections`` where
provider='unipile') carries ``{api_key, base_url}``. We resolve it under
``system_scope()`` (the key must never appear in the graph or logs) and send it
as the ``X-API-KEY`` header — the same scheme ``unipile.rs::unipile_creds`` uses.

Base URL shape: ``{base_url}/api/v1`` (developer.unipile.com). One ``_get`` /
``_post`` / ``_delete`` with the 429/5xx backoff pattern the source handlers use.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import httpx

from app.db import fetch_one, system_scope
from app.services.encryption import decrypt

log = logging.getLogger(__name__)

_TIMEOUT = 20.0
# Backoff for 429 / 5xx (mirrors the source handlers' retry theme).
_BACKOFF = (1.0, 3.0, 8.0)


class UnipileError(Exception):
    """A Unipile API call failed (network, auth, or non-2xx after retries)."""


class UnipileNotConfigured(UnipileError):
    """No usable Unipile connection for this workspace."""


class UnipileClient:
    """Thin async wrapper around one workspace's Unipile account.

    Construct via ``UnipileClient.for_workspace(workspace_id)`` which resolves the
    connection bundle. The base is stored WITHOUT a trailing slash; every method
    builds ``{base}/api/v1/...``.
    """

    def __init__(self, api_key: str, base_url: str) -> None:
        self._api_key = api_key
        self._base = base_url.rstrip("/")

    @classmethod
    async def for_workspace(cls, workspace_id: str, *, connection_name: str | None = None) -> UnipileClient:
        """Resolve the workspace's Unipile connection bundle → a client.

        Reads under system_scope() (the encrypted bundle is workspace-owned but
        the key resolution runs cross-scope like the dispatcher's). Raises
        ``UnipileNotConfigured`` when no unipile connection exists or the bundle
        lacks api_key/base_url."""
        async with system_scope():
            if connection_name:
                row = await fetch_one(
                    "SELECT credentials_encrypted FROM omni_connections "
                    "WHERE workspace_id=$1 AND provider='unipile' AND name=$2 "
                    "ORDER BY created_at DESC LIMIT 1",
                    workspace_id, connection_name,
                )
            else:
                row = await fetch_one(
                    "SELECT credentials_encrypted FROM omni_connections "
                    "WHERE workspace_id=$1 AND provider='unipile' "
                    "ORDER BY created_at DESC LIMIT 1",
                    workspace_id,
                )
        if not row:
            raise UnipileNotConfigured("no Unipile connection for this workspace")
        bundle = json.loads(decrypt(row["credentials_encrypted"]))
        api_key = bundle.get("api_key")
        base_url = bundle.get("base_url")
        if not api_key or not base_url:
            raise UnipileNotConfigured("Unipile connection bundle missing api_key/base_url")
        return cls(api_key, base_url)

    # ── HTTP primitives ────────────────────────────────────────────────────────
    def _url(self, path: str) -> str:
        return f"{self._base}/api/v1/{path.lstrip('/')}"

    async def _request(
        self, method: str, path: str, *, params: dict | None = None, json_body: dict | None = None
    ) -> Any:
        headers = {"X-API-KEY": self._api_key, "Accept": "application/json"}
        url = self._url(path)
        last_err: str | None = None
        for attempt in range(len(_BACKOFF) + 1):
            try:
                async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                    resp = await client.request(method, url, params=params, json=json_body, headers=headers)
            except httpx.HTTPError as e:
                last_err = f"network error: {e}"
                if attempt < len(_BACKOFF):
                    await asyncio.sleep(_BACKOFF[attempt])
                    continue
                raise UnipileError(last_err) from e
            if resp.status_code == 429 or resp.status_code >= 500:
                last_err = f"HTTP {resp.status_code}"
                if attempt < len(_BACKOFF):
                    await asyncio.sleep(_BACKOFF[attempt])
                    continue
                raise UnipileError(f"Unipile {method} {path} failed after retries: {last_err}")
            if resp.status_code >= 400:
                # Client error — don't retry, surface a bounded message (never the key).
                raise UnipileError(f"Unipile {method} {path} -> HTTP {resp.status_code}: {resp.text[:200]}")
            if not resp.content:
                return {}
            try:
                return resp.json()
            except json.JSONDecodeError:
                return {}
        raise UnipileError(last_err or "unknown error")

    async def _get(self, path: str, *, params: dict | None = None) -> Any:
        return await self._request("GET", path, params=params)

    async def _post(self, path: str, *, params: dict | None = None, json_body: dict | None = None) -> Any:
        return await self._request("POST", path, params=params, json_body=json_body)

    async def _delete(self, path: str, *, params: dict | None = None) -> Any:
        return await self._request("DELETE", path, params=params)

    async def _patch(self, path: str, *, json_body: dict | None = None) -> Any:
        return await self._request("PATCH", path, json_body=json_body)

    # ── Accounts (health / lifecycle) ──────────────────────────────────────────
    async def list_accounts(self) -> Any:
        return await self._get("accounts")

    async def get_account(self, account_id: str) -> Any:
        return await self._get(f"accounts/{account_id}")

    async def resync_account(self, account_id: str) -> Any:
        return await self._post(f"accounts/{account_id}/resync")

    async def reconnect_account(self, account_id: str) -> Any:
        return await self._post(f"accounts/{account_id}/reconnect")

    async def restart_account(self, account_id: str) -> Any:
        return await self._post(f"accounts/{account_id}/restart")

    # ── LinkedIn ───────────────────────────────────────────────────────────────
    async def inmail_balance(self, account_id: str) -> Any:
        return await self._get("linkedin/inmail-balance", params={"account_id": account_id})

    async def linkedin_search(self, account_id: str, body: dict, *, cursor: str | None = None) -> Any:
        params = {"account_id": account_id}
        if cursor:
            params["cursor"] = cursor
        return await self._post("linkedin/search", params=params, json_body=body)

    async def company_profile(self, account_id: str, company_id: str) -> Any:
        return await self._get(f"linkedin/company/{company_id}", params={"account_id": account_id})

    # ── Inbox (chats / messages) ───────────────────────────────────────────────
    async def list_chats(self, account_id: str, *, cursor: str | None = None, limit: int = 50) -> Any:
        params: dict[str, Any] = {"account_id": account_id, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._get("chats", params=params)

    async def get_chat(self, chat_id: str) -> Any:
        return await self._get(f"chats/{chat_id}")

    async def list_chat_messages(self, chat_id: str, *, cursor: str | None = None, limit: int = 50) -> Any:
        params: dict[str, Any] = {"limit": limit}
        if cursor:
            params["cursor"] = cursor
        return await self._get(f"chats/{chat_id}/messages", params=params)

    async def list_chat_attendees(self, chat_id: str) -> Any:
        return await self._get(f"chats/{chat_id}/attendees")

    # ── Native webhooks ────────────────────────────────────────────────────────
    async def register_webhook(self, url: str, events: list[str], *, name: str | None = None) -> Any:
        body: dict[str, Any] = {"request_url": url, "source": "messaging", "events": events}
        if name:
            body["name"] = name
        return await self._post("webhooks", json_body=body)

    async def list_webhooks(self) -> Any:
        return await self._get("webhooks")

    async def delete_webhook(self, webhook_id: str) -> Any:
        return await self._delete(f"webhooks/{webhook_id}")
