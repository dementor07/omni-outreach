"""Provider-neutral AI authoring for control-plane artifacts.

This module is deliberately separate from campaign execution. It resolves one
explicit, workspace-scoped connection and makes one text-generation call for a
validated artifact such as a ViewSpec. It never falls through to another
provider and never exposes decrypted credentials to a router or browser.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

import httpx

from app.db import fetch_all, fetch_one
from app.services.ai_jobs import AiJobError, _anthropic_text
from app.services.encryption import decrypt


class AuthoringProviderError(RuntimeError):
    """The selected authoring connection could not complete the request."""


@dataclass(frozen=True)
class AuthoringConnection:
    id: UUID
    provider: str
    name: str
    adapter: str
    api_key: str
    base_url: str
    default_model: str


_PROVIDER_DEFAULTS: dict[str, tuple[str, str, str]] = {
    # provider: (adapter, base_url, suggested model)
    "anthropic": ("anthropic", "", "claude-sonnet-4-20250514"),
    "openai": ("openai_responses", "https://api.openai.com", "gpt-5.4-mini"),
    "openrouter": ("openai_compatible", "https://openrouter.ai/api", "openai/gpt-5.4-mini"),
    "gemini": ("gemini", "https://generativelanguage.googleapis.com", "gemini-2.5-flash"),
    "openai_compatible": ("openai_compatible", "", ""),
}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _capability(provider: str, metadata: dict[str, Any]) -> tuple[str, str, str] | None:
    defaults = _PROVIDER_DEFAULTS.get(provider)
    if defaults:
        adapter, default_base_url, suggested_model = defaults
    elif str(metadata.get("api_compat") or "").lower() in {"openai", "openai_compatible"}:
        adapter, default_base_url, suggested_model = "openai_compatible", "", ""
    else:
        return None
    base_url = str(metadata.get("base_url") or default_base_url).strip().rstrip("/")
    model = str(metadata.get("default_model") or metadata.get("model") or suggested_model).strip()
    if adapter == "openai_compatible" and (not base_url or not model):
        return None
    return adapter, base_url, model


async def list_authoring_connections(workspace_id: str) -> list[dict[str, Any]]:
    """Return non-secret connected-AI capabilities for the authoring picker."""
    rows = await fetch_all(
        """
        SELECT id, provider, name, metadata
        FROM omni_connections
        WHERE workspace_id=$1
        ORDER BY connected_at DESC
        """,
        workspace_id,
    )
    result: list[dict[str, Any]] = []
    for row in rows:
        provider = str(row["provider"])
        capability = _capability(provider, _as_dict(row.get("metadata")))
        if not capability:
            continue
        adapter, _, default_model = capability
        result.append(
            {
                "id": row["id"],
                "provider": provider,
                "name": row["name"],
                "adapter": adapter,
                "default_model": default_model,
            }
        )
    return result


async def load_authoring_connection(workspace_id: str, connection_id: UUID) -> AuthoringConnection:
    row = await fetch_one(
        """
        SELECT id, provider, name, credentials_encrypted, metadata
        FROM omni_connections
        WHERE id=$1 AND workspace_id=$2
        """,
        connection_id,
        workspace_id,
    )
    if not row:
        raise AuthoringProviderError("selected AI connection was not found in this workspace")
    provider = str(row["provider"])
    metadata = _as_dict(row.get("metadata"))
    capability = _capability(provider, metadata)
    if not capability:
        raise AuthoringProviderError(
            f"{provider} is not configured for AI authoring; add a supported AI connection or OpenAI-compatible base URL and default model"
        )
    credentials = _as_dict(decrypt(row["credentials_encrypted"]))
    api_key = str(credentials.get("api_key") or "").strip()
    if not api_key:
        raise AuthoringProviderError("selected AI connection has no API key")
    adapter, base_url, default_model = capability
    return AuthoringConnection(
        id=row["id"],
        provider=provider,
        name=str(row["name"]),
        adapter=adapter,
        api_key=api_key,
        base_url=base_url,
        default_model=default_model,
    )


def _openai_output(data: dict[str, Any]) -> str:
    direct = data.get("output_text")
    if isinstance(direct, str) and direct.strip():
        return direct
    chunks: list[str] = []
    for output in data.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content") or []:
            if not isinstance(content, dict):
                continue
            text = content.get("text") or content.get("output_text")
            if isinstance(text, str):
                chunks.append(text)
    return "\n".join(chunks).strip()


def _chat_output(data: dict[str, Any]) -> str:
    choices = data.get("choices") or []
    if not choices or not isinstance(choices[0], dict):
        return ""
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text")) for part in content
            if isinstance(part, dict) and part.get("text")
        ).strip()
    return ""


def _gemini_output(data: dict[str, Any]) -> str:
    candidates = data.get("candidates") or []
    if not candidates or not isinstance(candidates[0], dict):
        return ""
    parts = ((candidates[0].get("content") or {}).get("parts") or [])
    return "\n".join(
        str(part.get("text")) for part in parts
        if isinstance(part, dict) and part.get("text")
    ).strip()


async def _post_json(url: str, *, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    try:
        async with httpx.AsyncClient(timeout=90.0) as client:
            response = await client.post(url, headers=headers, json=payload)
            response.raise_for_status()
            data = response.json()
    except httpx.HTTPStatusError as exc:
        raise AuthoringProviderError(f"selected provider returned HTTP {exc.response.status_code}") from exc
    except (httpx.HTTPError, ValueError) as exc:
        raise AuthoringProviderError("selected provider request failed") from exc
    if not isinstance(data, dict):
        raise AuthoringProviderError("selected provider returned an invalid response")
    return data


async def authoring_text(
    connection: AuthoringConnection,
    *,
    system: str,
    user: str,
    model: str | None,
    max_tokens: int,
) -> str:
    """Call exactly the selected provider and return its text output."""
    selected_model = (model or connection.default_model).strip()
    if not selected_model:
        raise AuthoringProviderError("choose a model for the selected AI connection")

    if connection.adapter == "anthropic":
        try:
            text, _usage = await _anthropic_text(
                connection.api_key, system, user, max_tokens, model=selected_model
            )
            return text
        except AiJobError as exc:
            raise AuthoringProviderError(f"selected Anthropic connection failed: {exc}") from exc

    if connection.adapter == "openai_responses":
        data = await _post_json(
            f"{connection.base_url}/v1/responses",
            headers={"Authorization": f"Bearer {connection.api_key}", "Content-Type": "application/json"},
            payload={
                "model": selected_model,
                "instructions": system,
                "input": user,
                "max_output_tokens": max_tokens,
            },
        )
        text = _openai_output(data)
    elif connection.adapter == "gemini":
        data = await _post_json(
            f"{connection.base_url}/v1beta/models/{selected_model}:generateContent?key={connection.api_key}",
            headers={"Content-Type": "application/json"},
            payload={
                "systemInstruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {
                    "maxOutputTokens": max_tokens,
                    "responseMimeType": "application/json",
                },
            },
        )
        text = _gemini_output(data)
    else:
        data = await _post_json(
            f"{connection.base_url}/v1/chat/completions",
            headers={"Authorization": f"Bearer {connection.api_key}", "Content-Type": "application/json"},
            payload={
                "model": selected_model,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                "max_tokens": max_tokens,
            },
        )
        text = _chat_output(data)

    if not text:
        raise AuthoringProviderError("selected provider returned no text")
    return text
