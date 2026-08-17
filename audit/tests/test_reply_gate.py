"""REPLY-GATE-001 — the HARD reply-stop, checked live at the send seam.

The reply poller closes the common case but leaves a race: a reply landing in
the poll gap while an operator approves the follow-up would ship a message after
the human already answered. This gate re-checks Unipile's authoritative thread
state at the instant of the send and refuses when the newest message is inbound —
so the send decision is correct regardless of poll latency. These lock that
decision (behaviour, not a string match).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[2] / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

import pytest

from app.execution import transition_worker as tw
from app.services.unipile_client import UnipileError


class _FakeClient:
    def __init__(self, items):
        self._items = items

    async def list_chat_messages(self, chat_id, *, cursor=None, limit=50):
        return {"items": self._items}


class _BoomClient:
    async def list_chat_messages(self, *a, **k):
        raise UnipileError("unipile down")


def _install(monkeypatch, *, items=None, read_error=False):
    calls: dict = {"process": [], "terminal": []}

    class FakeUnipile:
        @classmethod
        async def for_workspace(cls, ws, *, connection_name=None):
            return _BoomClient() if read_error else _FakeClient(items or [])

    async def fake_process(ws, cid, text, **kw):
        calls["process"].append((cid, text, kw))
        return {"intent": "neutral", "woke_leads": 0}

    async def fake_terminal(ws, lid, status, corr):
        calls["terminal"].append((lid, status))

    monkeypatch.setattr(tw, "UnipileClient", FakeUnipile)
    monkeypatch.setattr(tw.inbound_reply, "process_reply", fake_process)
    monkeypatch.setattr(tw, "_terminalize_lead", fake_terminal)
    return calls


_LEAD = {"id": "l1", "contact_id": "c1", "custom_fields": {"chat_id": "chatA"}}


@pytest.mark.asyncio
async def test_non_dm_channel_is_not_gated(monkeypatch):
    calls = _install(monkeypatch, items=[{"is_sender": 0, "id": "m1"}])
    handled = await tw._reply_gate_send("ws", _LEAD, {"id": "n1"}, "channel.linkedin_invite", "corr")
    assert handled is False and not calls["terminal"]


@pytest.mark.asyncio
async def test_first_dm_without_chat_id_proceeds(monkeypatch):
    # no open thread yet → nothing prior to reply to; the gate must not even call Unipile.
    calls = _install(monkeypatch, items=[{"is_sender": 0, "id": "m1"}])
    lead = {"id": "l1", "contact_id": "c1", "custom_fields": {}}
    handled = await tw._reply_gate_send("ws", lead, {"id": "n1"}, "channel.linkedin_dm", "corr")
    assert handled is False and not calls["process"]


@pytest.mark.asyncio
async def test_newest_is_our_send_proceeds(monkeypatch):
    calls = _install(monkeypatch, items=[{"is_sender": 1, "id": "m2", "text": "follow up"}])
    handled = await tw._reply_gate_send("ws", _LEAD, {"id": "n1"}, "channel.linkedin_dm", "corr")
    assert handled is False and not calls["terminal"]


@pytest.mark.asyncio
async def test_inbound_newest_suppresses_send_and_halts(monkeypatch):
    calls = _install(monkeypatch, items=[{"is_sender": 0, "id": "mX", "text": "stop pls"}])
    handled = await tw._reply_gate_send("ws", _LEAD, {"id": "n1"}, "channel.linkedin_dm", "corr")
    assert handled is True
    assert calls["terminal"] == [("l1", "completed")]
    assert calls["process"] and calls["process"][0][0] == "c1"
    assert calls["process"][0][2].get("source_message_id") == "mX"


@pytest.mark.asyncio
async def test_unipile_read_error_fails_open(monkeypatch):
    # cannot verify → proceed (the poller + approval gate are backstops; a real
    # Unipile outage would fail the send itself anyway). Never blocks blindly.
    calls = _install(monkeypatch, read_error=True)
    handled = await tw._reply_gate_send("ws", _LEAD, {"id": "n1"}, "channel.linkedin_dm", "corr")
    assert handled is False and not calls["terminal"]


@pytest.mark.asyncio
async def test_missing_is_sender_is_not_a_reply(monkeypatch):
    calls = _install(monkeypatch, items=[{"id": "m?"}])
    handled = await tw._reply_gate_send("ws", _LEAD, {"id": "n1"}, "channel.linkedin_dm", "corr")
    assert handled is False and not calls["terminal"]
