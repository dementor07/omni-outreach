"""REPLY-POLL-001 — poll-based reply detection (the reliable reply-stop path).

Unipile push webhooks did not reliably deliver LinkedIn replies (a real reply
fired the webhook but carried no resolvable sender, so no lead woke). The
unipile_sync worker polls in-flight threads instead and halts the sequence when
the newest message is inbound. These lock the DECISION (behaviour, not a string
match): the detector fires exactly when the newest message is a fresh inbound,
and never on our own sends or an already-processed reply.

The Unipile message shape used here is the REAL one (probed live):
``is_sender`` is 1 for our seat's sends and 0 for inbound, messages are
newest-first, each with an ``id``.
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


class _FakeClient:
    """Stands in for UnipileClient — returns a scripted messages payload."""

    def __init__(self, items):
        self._items = items

    async def list_chat_messages(self, chat_id, *, cursor=None, limit=50):
        return {"object": "MessageList", "items": self._items}


def _run(lead, items, *, seen_contacts=None):
    """Drive _check_lead with process_reply + the DB stamp stubbed; return
    (woke_count, list-of-process_reply-calls, stamped-msg-ids)."""
    calls: list = []
    stamped: list = []

    async def fake_process_reply(ws, contact_id, text, **kw):
        calls.append({"ws": ws, "contact_id": contact_id, "text": text, **kw})
        return {"intent": "neutral", "confidence": 0.5, "woke_leads": 1}

    async def fake_stamp(ws, lead_id, msg_id):
        stamped.append(msg_id)

    async def go():
        # patch the collaborators the worker calls
        orig_pr = usw.inbound_reply.process_reply
        orig_stamp = usw._stamp_reply_seen
        usw.inbound_reply.process_reply = fake_process_reply
        usw._stamp_reply_seen = fake_stamp
        try:
            return await usw._check_lead(
                _FakeClient(items), "ws1", lead,
                sem=asyncio.Semaphore(2), lock=asyncio.Lock(),
                woken_contacts=set(seen_contacts or []),
            )
        finally:
            usw.inbound_reply.process_reply = orig_pr
            usw._stamp_reply_seen = orig_stamp

    woke = asyncio.run(go())
    return woke, calls, stamped


_LEAD = {"id": "l1", "workspace_id": "ws1", "contact_id": "c1", "chat_id": "chatA", "reply_seen": None}


def test_our_own_send_does_not_fire():
    # newest message is our seat's send (is_sender=1) → no reply, no wake.
    items = [{"id": "m2", "is_sender": 1, "text": "Just following up"},
             {"id": "m1", "is_sender": 0, "text": "old reply"}]
    woke, calls, _ = _run(_LEAD, items)
    assert woke == 0 and calls == []


def test_fresh_inbound_fires_the_halt():
    # newest message is inbound (is_sender=0) and unseen → fire process_reply once.
    items = [{"id": "mX", "is_sender": 0, "text": "Interrupt test #1"},
             {"id": "m1", "is_sender": 1, "text": "Thanks for connecting"}]
    woke, calls, stamped = _run(_LEAD, items)
    assert woke == 1
    assert len(calls) == 1
    assert calls[0]["contact_id"] == "c1"
    assert calls[0]["source_message_id"] == "mX"
    assert "mX" in stamped  # high-water mark recorded


def test_already_processed_reply_does_not_refire():
    # newest inbound id equals the lead's stored high-water mark → skip.
    lead = {**_LEAD, "reply_seen": "mX"}
    items = [{"id": "mX", "is_sender": 0, "text": "Interrupt test #1"}]
    woke, calls, _ = _run(lead, items)
    assert woke == 0 and calls == []


def test_missing_is_sender_is_not_treated_as_reply():
    # defensive: an ambiguous shape (no is_sender) must NOT halt — never guess.
    items = [{"id": "mZ", "text": "who knows"}]
    woke, calls, _ = _run(_LEAD, items)
    assert woke == 0 and calls == []


def test_empty_thread_is_noop():
    woke, calls, _ = _run(_LEAD, [])
    assert woke == 0 and calls == []


def test_contact_already_woken_this_cycle_is_skipped_but_stamped():
    # a second waiting lead for the same contact in one sweep → don't double-fire
    # process_reply, but still stamp so it isn't reconsidered next cycle.
    items = [{"id": "mX", "is_sender": 0, "text": "reply"}]
    woke, calls, stamped = _run(_LEAD, items, seen_contacts={"c1"})
    assert woke == 0 and calls == []
    assert "mX" in stamped


# ── acceptance sweep — advance parked invites when the connection lands ────────


class _ProfClient:
    def __init__(self, prof):
        self._prof = prof

    async def member_profile(self, account_id, public_id):
        return self._prof


def _run_accept(lead, prof):
    """Drive _check_acceptance with resume_on_signal stubbed; return
    (resumed_count, list-of-resume-calls)."""
    calls: list = []

    async def fake_resume(ws, lead_id, signal, **kw):
        calls.append({"ws": ws, "lead_id": lead_id, "signal": signal})
        return True

    async def go():
        orig = usw.event_resume.resume_on_signal
        usw.event_resume.resume_on_signal = fake_resume
        try:
            import asyncio as _a
            return await usw._check_acceptance(
                _ProfClient(prof), "ws1", lead, sem=_a.Semaphore(2)
            )
        finally:
            usw.event_resume.resume_on_signal = orig

    return asyncio.run(go()), calls


_INVITE_LEAD = {
    "id": "il1", "workspace_id": "ws1", "account_id": "seatA",
    "linkedin_url": "https://www.linkedin.com/in/navin-john-antony-a58a00335/",
}


def test_public_id_strips_trailing_slash_and_lowercases():
    assert usw._public_id("https://www.linkedin.com/in/Navin-John/") == "navin-john"
    assert usw._public_id(None) is None


def test_first_degree_resumes_the_parked_invite():
    resumed, calls = _run_accept(_INVITE_LEAD, {"network_distance": "FIRST_DEGREE"})
    assert resumed == 1
    assert calls and calls[0]["signal"] == "invite_accepted" and calls[0]["lead_id"] == "il1"


def test_is_relationship_true_also_resumes():
    resumed, calls = _run_accept(_INVITE_LEAD, {"is_relationship": True})
    assert resumed == 1 and calls


def test_not_connected_does_not_resume():
    # 2nd-degree / pending invite → no advance, no guess.
    resumed, calls = _run_accept(_INVITE_LEAD, {"network_distance": "SECOND_DEGREE", "is_relationship": False})
    assert resumed == 0 and calls == []


def test_missing_distance_is_not_treated_as_accepted():
    resumed, calls = _run_accept(_INVITE_LEAD, {"first_name": "Navin"})
    assert resumed == 0 and calls == []
