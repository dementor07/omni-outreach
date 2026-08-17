"""B3 regression — inbox reply: AI-suggested draft + DNC-checked send.

Two contracts:
  1. reply_drafter.suggest_reply FAILS OPEN — with no anthropic connection it
     returns an intent-shaped template (never an empty box, never raises).
  2. The /inbox reply endpoint is still an OUTBOUND send, so the T1 DNC gate
     applies: a suppressed contact's reply must be REFUSED before any command
     is published to the muscle. Verified at source level (the seam shape is
     what guarantees it under the synthetic-lead manual-reply path).

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.services import reply_drafter

BACKEND = Path(__file__).resolve().parents[2] / "backend"
INBOX = (BACKEND / "app" / "routers" / "inbox.py").read_text(encoding="utf-8")


# ── drafter: fail-open template path (no anthropic connection) ────────────────

def test_template_for_known_intents():
    assert "call" in reply_drafter._template_for("positive").lower()
    assert reply_drafter._template_for("objection")
    # unknown / None intent falls back to the neutral template
    assert reply_drafter._template_for(None) == reply_drafter._DEFAULT_TEMPLATE
    assert reply_drafter._template_for("garbage") == reply_drafter._DEFAULT_TEMPLATE


def test_transcript_renders_us_them_and_skips_empty():
    msgs = [
        {"direction": "inbound", "body": "Tell me more"},
        {"direction": "outbound", "body": ""},
        {"direction": "outbound", "body": "Sure, here are the details"},
    ]
    t = reply_drafter._transcript(msgs)
    assert "Them: Tell me more" in t
    assert "Us: Sure, here are the details" in t
    assert t.count("\n") == 1  # the empty outbound body is skipped


def test_suggest_reply_fails_open_to_template(monkeypatch):
    # no anthropic key → deterministic template, no network, no raise.
    async def _no_key(_ws):
        return None

    monkeypatch.setattr(reply_drafter, "_anthropic_key", _no_key)
    draft, source = asyncio.run(
        reply_drafter.suggest_reply("ws", [{"direction": "inbound", "body": "Interested!"}], "positive")
    )
    assert source == "template"
    assert draft == reply_drafter._TEMPLATES["positive"]


# ── wire-in: the reply endpoint enforces DNC before dispatch ──────────────────

def test_reply_endpoint_checks_dnc_before_publish():
    body = INBOX.split("async def send_reply", 1)[1]
    assert "suppression.is_suppressed" in body, "reply send must re-check DNC"
    sup_pos = body.find("is_suppressed")
    pub_pos = body.find("publish_command")
    assert sup_pos != -1 and pub_pos != -1
    assert sup_pos < pub_pos, "DNC check must precede the muscle dispatch"
    # a suppressed contact is refused, not silently sent.
    guard = body[sup_pos:pub_pos]
    assert "409" in guard, "a suppressed reply must 409, not dispatch"


def test_reply_endpoint_dispatches_through_the_muscle():
    body = INBOX.split("async def send_reply", 1)[1]
    # congruity: a manual reply rides the same spine — build_command + publish.
    assert "commands.build_command" in body
    assert "commands.publish_command" in body


def test_suggest_endpoint_exists_and_is_fail_open():
    assert "async def suggest_reply" in INBOX
    assert "reply_drafter.suggest_reply" in INBOX
