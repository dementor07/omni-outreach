"""INBOX-DISCOVER-001 / INBOX-REPLY-001 — why the inbox showed no replies.

Measured against the live workspace before the fix: 249 Unipile chats existed
across the seats, 85 of them contained an inbound message, and exactly 14 were
linked to a lead. omni_messages held 2 rows, both from twelve days earlier.

Two gates were starving it:
  * chat_id was only ever written when OUR outbound DM opened a chat, so anyone
    who replied after accepting an invite was invisible;
  * the sweep only opened a chat when unread_count > 0, so a reply already read
    on a phone was never recorded, and only leads still in status='waiting'
    were considered at all.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.execution import unipile_sync_worker as worker  # noqa: E402

WORKER_SRC = (ROOT / "backend/app/execution/unipile_sync_worker.py").read_text(encoding="utf-8")
INBOX_SRC = (ROOT / "backend/app/routers/inbox.py").read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_an_unlinked_chat_is_matched_to_its_contact(monkeypatch):
    """attendee_provider_id is already in the chat list, so linking costs no
    extra API call and never views a profile."""
    captured = {}

    async def fake_fetch_all(query, *args):
        captured["query"] = query
        captured["args"] = args
        return [{"id": "lead-1"}]

    monkeypatch.setattr(worker, "fetch_all", fake_fetch_all)
    n = await worker._link_chat_to_lead(
        "ws-1", {"id": "chatXYZ", "attendee_provider_id": "ACoAAA_member_123"}
    )
    assert n == 1
    assert captured["args"] == ("ws-1", "ACoAAA_member_123", "chatXYZ")
    # It must only fill an EMPTY chat_id, never overwrite a live one.
    assert "COALESCE(l.custom_fields->>'chat_id', '') = ''" in captured["query"]
    assert "c.custom_fields->>'provider_id' = $2" in captured["query"]


@pytest.mark.asyncio
async def test_a_chat_without_an_attendee_id_is_skipped(monkeypatch):
    async def explode(*_a, **_k):
        raise AssertionError("must not query without an attendee id")

    monkeypatch.setattr(worker, "fetch_all", explode)
    assert await worker._link_chat_to_lead("ws", {"id": "c1"}) == 0
    assert await worker._link_chat_to_lead("ws", {"attendee_provider_id": "x"}) == 0


def test_reply_sweep_is_no_longer_limited_to_waiting_leads():
    """A lead whose sequence completed can still be replied to, and that reply
    belongs in the inbox."""
    sweep = WORKER_SRC.split("async def run_reply_sweep")[1].split("async def ")[0]
    assert "l.status = 'waiting'" not in sweep
    assert "COALESCE(l.custom_fields->>'chat_id', '') <> ''" in sweep


def test_a_read_reply_is_still_detected():
    """unread_count alone missed every reply the operator had already opened on
    their phone. The chat timestamp moving is the honest signal."""
    sweep = WORKER_SRC.split("async def run_reply_sweep")[1].split("async def ")[0]
    assert 'moved = bool(stamp) and stamp != (lead.get("chat_seen_ts") or "")' in sweep
    assert 'int(chat.get("unread_count") or 0) > 0 or moved' in sweep


def test_an_unlinked_chat_triggers_discovery_inside_the_same_sweep():
    """Discovery must reuse the chat list the sweep already fetched; a second
    pass would double the per-seat API cost this worker exists to bound."""
    sweep = WORKER_SRC.split("async def run_reply_sweep")[1].split("async def ")[0]
    assert "_link_chat_to_lead(ws, chat)" in sweep
    # Count real invocations, not the string inside the failure log line.
    assert sweep.count("client.list_chats(") == 1


def test_the_watermark_records_the_chat_timestamp():
    assert '"chat_seen_ts"' in WORKER_SRC
    assert '"reply_seen_msg_id"' in WORKER_SRC


def test_thread_list_collapses_invites_like_the_thread_detail_does():
    """The list said Vijay had 4 messages while the detail returned 3, because
    duplicate invite rows in the send ledger were counted but not rendered."""
    assert "DISTINCT ON (contact_id, channel)" in INBOX_SRC
    assert re.search(r"channel LIKE '%invite%' OR channel LIKE '%profile_view%'", INBOX_SRC)
    assert re.search(
        r"channel NOT LIKE '%invite%' AND channel NOT LIKE '%profile_view%'", INBOX_SRC
    )


def test_discovery_never_views_a_profile():
    """Profile views on a timer were the real ban vector; the linker must stay
    inside data the chat list already returned."""
    linker = WORKER_SRC.split("async def _link_chat_to_lead")[1].split("async def ")[0]
    for banned in ("member_profile", "get_profile", "profile_view"):
        assert banned not in linker
