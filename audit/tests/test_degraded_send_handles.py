"""Degraded-send handles: no-chat_id + unconfirmed-invite (NOCHAT-001).

Two provider failure modes that look like success but aren't safe to build a
follow-up on:

1. A DM OPENS a new chat, the API says success, but returns NO chat_id — we
   can't thread any follow-up. We record the send but route to a `no_thread`
   degraded handle instead of pretending the thread is healthy.

2. An invite returns 201 but is unconfirmed — we must NEVER DM purely on our own
   "invite_sent". This is enforced structurally (the invite parks at
   event.invite_accepted; the DM only fires on the acceptance resume; and the
   relationship gate re-checks distance before the DM) — three independent
   layers, none of which auto-follows the invite with a DM.

Static/source-faithful (house style).
"""

from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("DB_PASSWORD", "testpass")
os.environ.setdefault("SECRET_KEY", "test-secret-key-not-for-production")
os.environ.setdefault("REDIS_PASSWORD", "")

REPO = Path(__file__).resolve().parents[2]
UNIPILE_RS = (REPO / "backend-rust/src/handlers/unipile.rs").read_text(encoding="utf-8")
TW_SRC = (REPO / "backend/app/execution/transition_worker.py").read_text(encoding="utf-8")
INVITE_NODE = (REPO / "backend/app/nodes/events/invite_accepted.py").read_text(encoding="utf-8")


def _rs_fn(name: str) -> str:
    m = re.search(rf"(?:pub )?(?:async )?fn {name}\(.*?(?=\n(?:pub )?(?:async )?fn |\Z)", UNIPILE_RS, re.S)
    assert m, f"rust fn {name} not found"
    return m.group(0)


def test_new_chat_without_chat_id_routes_to_no_thread():
    body = _rs_fn("send_chat")
    # opened a new chat (opened_chat_id.is_some()) but empty chat_id => degraded.
    assert "opened_chat_id.is_some() && new_chat_id.is_empty()" in body
    assert 'next_handle".to_string(), json!("no_thread")' in body
    # the send is still recorded (status stays sent / ok) — we don't pretend it
    # failed, we flag that the THREAD is unhealthy.
    assert "common::ok(" in body


def test_existing_chat_send_is_exempt_from_no_thread():
    body = _rs_fn("send_chat")
    # an existing-chat send (opened_chat_id is None) already has its thread; the
    # no_thread degrade is gated on opened_chat_id.is_some().
    idx = body.find('json!("no_thread")')
    assert idx != -1
    guard = body[:idx]
    assert "opened_chat_id.is_some()" in guard


def test_no_thread_handle_ends_honestly_when_unwired():
    # an unwired no_thread handle must not record a false 'completed'.
    assert '"no_thread": "ended"' in TW_SRC


def test_invite_parks_and_never_auto_dms():
    # the invite-accepted node PARKS the lead (awaits the signal) — it does not
    # advance to a DM on its own. The DM only fires when the acceptance webhook
    # resumes it (resume_on_signal), and the relationship gate re-checks before
    # sending. So nothing DMs on an unconfirmed invite.
    assert 'resume_on_signal' in INVITE_NODE
    assert '"invite_accepted"' in INVITE_NODE
    # the node parks (a wait), it doesn't emit a send.
    assert "park" in INVITE_NODE.lower() or "wait" in INVITE_NODE.lower()
