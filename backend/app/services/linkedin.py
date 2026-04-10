"""Async Unipile API wrapper for LinkedIn operations."""
import logging

import httpx

from app.config import settings

log = logging.getLogger(__name__)


class InvalidRecipientError(RuntimeError):
    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.detail = detail


def _headers(json: bool = True) -> dict:
    h = {"accept": "application/json", "X-API-KEY": settings.unipile_api_key}
    if json:
        h["content-type"] = "application/json"
    return h


def _base() -> str:
    return settings.unipile_base.rstrip("/")


def _handle(resp: httpx.Response, action: str) -> dict:
    if not resp.is_success:
        data: dict | None = None
        try:
            data = resp.json()
        except Exception:
            pass
        if (
            resp.status_code == 422
            and isinstance(data, dict)
            and data.get("type") in ("errors/invalid_recipient", "errors/blocked_recipient")
        ):
            raise InvalidRecipientError(
                f"[unipile:{action}] {data.get('detail', 'invalid_recipient')}",
                detail=data.get("detail"),
            )
        raise RuntimeError(f"[unipile:{action}] status={resp.status_code} body={resp.text}")
    try:
        return resp.json()
    except Exception:
        raise RuntimeError(f"[unipile:{action}] invalid JSON: {resp.text}")


async def get_profile(public_identifier: str, account_id: str) -> dict:
    if not public_identifier:
        raise ValueError("public_identifier is required")
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.get(
            f"{_base()}/api/v1/users/{public_identifier}",
            headers=_headers(json=False),
            params={"account_id": account_id},
        )
    return _handle(resp, "get_profile")


async def send_invite(account_id: str, provider_id: str) -> dict:
    if not provider_id:
        raise ValueError("provider_id is required")
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(
            f"{_base()}/api/v1/users/invite",
            json={"account_id": account_id, "provider_id": provider_id},
            headers=_headers(),
        )
    return _handle(resp, "send_invite")


async def start_chat_with_message(account_id: str, provider_id: str, message: str) -> dict:
    """Open a LinkedIn chat and send the first message atomically. Returns {"chat_id": ...}."""
    if not message.strip():
        raise ValueError("message cannot be empty")
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(
            f"{_base()}/api/v1/chats",
            headers=_headers(json=False),
            files={
                "account_id": (None, account_id),
                "attendees_ids": (None, provider_id),
                "text": (None, message),
            },
        )
    data = _handle(resp, "start_chat_with_message")
    if not data.get("chat_id"):
        raise RuntimeError(f"[unipile:start_chat_with_message] chat_id missing: {data}")
    return data


async def send_message(chat_id: str, message: str, account_id: str, provider_id: str) -> dict:
    """Send a follow-up message in an existing chat."""
    if not chat_id:
        raise ValueError("chat_id is required")
    if not message.strip():
        raise ValueError("message cannot be empty")
    async with httpx.AsyncClient(timeout=40) as client:
        resp = await client.post(
            f"{_base()}/api/v1/chats/{chat_id}/messages",
            headers=_headers(json=False),
            files={
                "account_id": (None, account_id),
                "attendee_id": (None, provider_id),
                "text": (None, message),
            },
        )
    return _handle(resp, "send_message")
