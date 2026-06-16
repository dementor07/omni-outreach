"""B2 regression — reply intent classification (single LLM call + keyword fallback).

Per the researched industry pattern: a bounded LLM call fail-open to a
deterministic keyword heuristic, with provenance. These cover the pure keyword
path (which is also the LLM-unavailable fallback) + the wire-in invariants that
the inbound reply webhook classifies, auto-suppresses unsubscribes, and emits a
reply→wake-up transition.

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

from pathlib import Path

from app.services.reply_classifier import INTENTS, _force_unsubscribe, _keyword_classify

BACKEND = Path(__file__).resolve().parents[2] / "backend"


# ── keyword classifier (the fail-open path) ──────────────────────────────────

def test_unsubscribe_always_detected():
    for body in ("Please unsubscribe me", "STOP emailing me", "remove me from your list", "do not contact"):
        intent, conf = _keyword_classify(body)
        assert intent == "unsubscribe" and conf >= 0.9
        assert _force_unsubscribe(body)


def test_positive_objection_question_neutral():
    assert _keyword_classify("This sounds good, let's talk")[0] == "positive"
    assert _keyword_classify("Not interested, thanks")[0] == "objection"
    assert _keyword_classify("How much does it cost?")[0] == "question"
    assert _keyword_classify("Out of office until Monday")[0] == "neutral"


def test_intents_contract():
    assert INTENTS == ("positive", "question", "objection", "unsubscribe", "neutral")


def test_force_unsubscribe_is_independent_of_sentiment():
    # an opt-out buried in otherwise-positive text must still force unsubscribe
    assert _force_unsubscribe("Loved it but please remove me from your list")


# ── wire-in: the inbound reply webhook ───────────────────────────────────────

def test_reply_webhook_classifies_suppresses_and_wakes():
    src = (BACKEND / "app" / "routers" / "webhooks_in.py").read_text(encoding="utf-8")
    body = src.split("async def receive_reply", 1)[1]
    assert "reply_classifier.classify_reply" in body, "reply must be classified"
    assert "message.received" in body, "reply must record message.received with classification"
    # unsubscribe auto-writes the T1 suppression list
    assert "omni_suppression_list" in body and "'unsubscribe'" in body
    # SM-8 reply→wake-up: a waiting lead is woken off the 'replied' handle
    assert "status='waiting'" in body
    assert '"replied"' in body or "'replied'" in body
    assert "TRANSITIONS_TOPIC" in body


def test_reply_webhook_requires_hmac():
    src = (BACKEND / "app" / "routers" / "webhooks_in.py").read_text(encoding="utf-8")
    body = src.split("async def receive_reply", 1)[1].split("async def ", 1)[0]
    assert "_verify_hmac" in body and "401" in body, "inbound replies must verify HMAC"
