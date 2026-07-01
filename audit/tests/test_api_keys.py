"""N8N-001 Part 1 — API-key generation/hash/lookup + RLS-scope arming.

Pure/mocked: no DB connection. We verify the key format, the hash-only storage
invariant, that a revoked/wrong key 401s, and that a valid key ends in
``set_request_workspace`` (arming RLS for the resolved workspace) — the whole
tenant boundary rests on that call.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app import auth_apikey  # noqa: E402
from app.auth_apikey import (  # noqa: E402
    _resolve_key_workspace,
    generate_api_key,
    hash_api_key,
)


def test_key_format_and_hash_roundtrip():
    raw, prefix, key_hash = generate_api_key()
    assert raw.startswith("omni_sk_")
    assert prefix.startswith("omni_sk_")
    # The prefix is a DISPLAY prefix — never the whole key.
    assert len(prefix) < len(raw)
    assert raw.startswith(prefix)
    # Hash is sha256 hex of the raw key, and it's what we persist (never the raw).
    assert key_hash == hash_api_key(raw)
    assert len(key_hash) == 64
    assert raw not in key_hash


def test_two_keys_are_distinct():
    a, _, ha = generate_api_key()
    b, _, hb = generate_api_key()
    assert a != b and ha != hb


@pytest.mark.asyncio
async def test_valid_key_arms_workspace_and_returns_context(monkeypatch):
    """A live key resolves its workspace, arms RLS (set_request_workspace), and
    returns an AuthContext carrying that workspace."""
    raw, _prefix, key_hash = generate_api_key()
    ws = "11111111-1111-1111-1111-111111111111"

    async def fake_fetch_one(query, *args):
        assert args[0] == key_hash  # lookup is by hash, not the raw key
        return {
            "id": "key-1",
            "workspace_id": ws,
            "key_hash": key_hash,
            "created_by": "user-9",
            "revoked_at": None,
        }

    async def fake_execute(query, *args):
        return "UPDATE 1"

    armed: dict[str, str] = {}
    monkeypatch.setattr(auth_apikey, "fetch_one", fake_fetch_one)
    monkeypatch.setattr(auth_apikey, "execute", fake_execute)
    monkeypatch.setattr(auth_apikey, "set_request_workspace", lambda w: armed.__setitem__("ws", w))

    ctx = await _resolve_key_workspace(raw)
    assert ctx.workspace_id == ws
    assert ctx.user_id == "user-9"
    assert armed.get("ws") == ws, "a valid key must arm RLS via set_request_workspace"


@pytest.mark.asyncio
async def test_revoked_key_is_401(monkeypatch):
    from fastapi import HTTPException

    raw, _prefix, key_hash = generate_api_key()

    async def fake_fetch_one(query, *args):
        return {
            "id": "k", "workspace_id": "w", "key_hash": key_hash,
            "created_by": None, "revoked_at": "2026-01-01T00:00:00Z",
        }

    monkeypatch.setattr(auth_apikey, "fetch_one", fake_fetch_one)
    with pytest.raises(HTTPException) as ei:
        await _resolve_key_workspace(raw)
    assert ei.value.status_code == 401


@pytest.mark.asyncio
async def test_unknown_key_is_401(monkeypatch):
    from fastapi import HTTPException

    raw, _prefix, _hash = generate_api_key()

    async def fake_fetch_one(query, *args):
        return None  # no matching hash

    monkeypatch.setattr(auth_apikey, "fetch_one", fake_fetch_one)
    with pytest.raises(HTTPException) as ei:
        await _resolve_key_workspace(raw)
    assert ei.value.status_code == 401


def test_extract_api_key_prefers_omni_sk():
    """The extractor recognises omni_sk_ in Authorization: Bearer and X-API-Key,
    and returns None (fall through to JWT) when neither carries an omni_sk_ key."""
    from types import SimpleNamespace

    from fastapi.security import HTTPAuthorizationCredentials

    key = "omni_sk_abc123"
    bearer = HTTPAuthorizationCredentials(scheme="Bearer", credentials=key)
    req = SimpleNamespace(headers={})
    assert auth_apikey._extract_api_key(req, bearer) == key

    # X-API-Key header path
    req2 = SimpleNamespace(headers={"x-api-key": key})
    assert auth_apikey._extract_api_key(req2, None) == key

    # A JWT (not an omni_sk_) in the bearer → None so the JWT path takes over.
    jwt_cred = HTTPAuthorizationCredentials(scheme="Bearer", credentials="eyJhbGciOi.jwt")
    req3 = SimpleNamespace(headers={})
    assert auth_apikey._extract_api_key(req3, jwt_cred) is None
