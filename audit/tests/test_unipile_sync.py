"""REPLY-POLL-001 / ACCEPT-POLL-001 — poll-based detection, O(seats) + cheap.

Unipile is billed per call and LinkedIn flags accounts that overdo a mechanism
(profile views especially). So both sweeps are O(seats), not O(leads), and
acceptance uses the connections LIST (one call/seat), never a per-lead profile
view. These lock the decision primitives (behaviour, not string matches).
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

_BACKEND = str(Path(__file__).resolve().parents[2] / "backend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

from app.execution import unipile_sync_worker as usw


# ── pure helpers ──────────────────────────────────────────────────────────────


def test_public_id_strips_slash_and_lowercases():
    assert usw._public_id("https://www.linkedin.com/in/Navin-John/") == "navin-john"
    assert usw._public_id(None) is None


def test_seat_ids_is_shape_tolerant():
    assert usw._seat_ids({"items": [{"id": "a"}, {"id": "b"}, {"nope": 1}]}) == ["a", "b"]
    assert usw._seat_ids([{"id": "c"}]) == ["c"]
    assert usw._seat_ids(None) == []


def test_jitter_stays_in_band_and_floored():
    for base in (180, 1800):
        for _ in range(50):
            v = usw._jittered(base)
            assert base * 0.75 <= v <= base * 1.25
    assert usw._jittered(10) >= 30.0  # floor


# ── acceptance match: by provider_id OR url slug, explicit only ──────────────


def test_relation_match_by_provider_id():
    assert usw._relation_matches("ACoAAF123", None, {"ACoAAF123"}) is True


def test_relation_match_by_url_slug():
    assert usw._relation_matches(None, "https://www.linkedin.com/in/navin-john-antony/", {"navin-john-antony"}) is True


def test_relation_no_match_when_absent():
    assert usw._relation_matches("X", "https://www.linkedin.com/in/y/", {"other"}) is False


def test_relation_no_match_on_empty_identity():
    # a parked invite with no provider_id and no url can never spuriously match.
    assert usw._relation_matches("", None, {"", "anything"}) is False


# ── _relations_id_set: one call, indexes member_id + public_identifier ───────


class _RelClient:
    def __init__(self, items):
        self._items = items
        self.calls = 0

    async def list_relations(self, account_id, *, cursor=None, limit=50):
        self.calls += 1
        return {"items": self._items}


def test_relations_id_set_indexes_both_ids_one_call():
    c = _RelClient([
        {"member_id": "ACoAAF1", "public_identifier": "Navin-John"},
        {"member_id": "ACoAAF2", "public_identifier": None},
    ])
    ids = asyncio.run(usw._relations_id_set(c, "seatA"))
    assert ids == {"ACoAAF1", "navin-john", "ACoAAF2"}  # public_id lowercased
    assert c.calls == 1  # ONE call per seat — the whole point


# ── reply detection: newest inbound → halt; else proceed ─────────────────────


class _MsgClient:
    def __init__(self, items):
        self._items = items

    async def list_chat_messages(self, chat_id, *, cursor=None, limit=50):
        return {"items": self._items}


def _run_reply(lead, items):
    calls = {"process": [], "stamp": []}

    class _Scope:
        async def __aenter__(self):
            return None

        async def __aexit__(self, *a):
            return False

    async def fake_execute(*a, **k):
        calls["stamp"].append(a)

    async def fake_process(ws, cid, text, **kw):
        calls["process"].append((cid, kw.get("source_message_id")))
        return {"intent": "neutral", "woke_leads": 1}

    async def go():
        o_scope, o_exec, o_proc = usw.system_scope, usw.execute, usw.inbound_reply.process_reply
        usw.system_scope = lambda: _Scope()
        usw.execute = fake_execute
        usw.inbound_reply.process_reply = fake_process
        try:
            return await usw._process_reply_for_lead(_MsgClient(items), "ws", lead)
        finally:
            usw.system_scope, usw.execute, usw.inbound_reply.process_reply = o_scope, o_exec, o_proc

    return asyncio.run(go()), calls


_LEAD = {"id": "l1", "contact_id": "c1", "chat_id": "chatA", "reply_seen": None}


def test_inbound_newest_halts_and_stamps():
    woke, calls = _run_reply(_LEAD, [{"id": "mX", "is_sender": 0, "text": "hi"}])
    assert woke == 1
    assert calls["process"] == [("c1", "mX")]
    assert calls["stamp"]  # high-water mark written


def test_our_send_newest_proceeds():
    woke, calls = _run_reply(_LEAD, [{"id": "m2", "is_sender": 1, "text": "follow up"}])
    assert woke == 0 and not calls["process"]


def test_already_seen_reply_not_refired():
    lead = {**_LEAD, "reply_seen": "mX"}
    woke, calls = _run_reply(lead, [{"id": "mX", "is_sender": 0, "text": "hi"}])
    assert woke == 0 and not calls["process"]


def test_missing_is_sender_not_a_reply():
    woke, calls = _run_reply(_LEAD, [{"id": "m?", "text": "?"}])
    assert woke == 0 and not calls["process"]
