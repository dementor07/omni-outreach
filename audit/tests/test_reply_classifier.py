"""B2 regression — reply intent classification.

The LLM call was moved OFF the Python request path into the Rust muscle's
`ai.classify` handler (rust-python-boundary-audit). The Python side is now a
pure, synchronous keyword classifier the inbound webhook calls inline — opt-out
detection MUST be synchronous (compliance) and is deterministic anyway. These
cover the pure keyword path + the wire-in invariants (webhook classifies,
auto-suppresses unsubscribes, wakes waiting leads) + the boundary invariant
(no Anthropic HTTP call left in Python; the Rust handler owns it).

Run from backend/:
  PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
    REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q
"""

from __future__ import annotations

from pathlib import Path

from app.services.reply_classifier import INTENTS, classify_reply

BACKEND = Path(__file__).resolve().parents[2] / "backend"
REPO = BACKEND.parent


# ── pure keyword classifier (synchronous, no I/O) ────────────────────────────

def test_unsubscribe_always_detected():
    for body in ("Please unsubscribe me", "STOP emailing me", "remove me from your list", "do not contact"):
        intent, conf, _reason, source = classify_reply(body)
        assert intent == "unsubscribe" and conf >= 0.9
        assert source == "keyword"


def test_positive_objection_question_neutral():
    assert classify_reply("This sounds good, let's talk")[0] == "positive"
    assert classify_reply("Not interested, thanks")[0] == "objection"
    assert classify_reply("How much does it cost?")[0] == "question"
    assert classify_reply("Out of office until Monday")[0] == "neutral"


def test_intents_contract():
    assert INTENTS == ("positive", "question", "objection", "unsubscribe", "neutral")


def test_classify_reply_is_synchronous_and_pure():
    # No coroutine, no args beyond the body — it must be safe to call inline in
    # the request path. (A coroutine here would mean the LLM call crept back.)
    import inspect

    assert not inspect.iscoroutinefunction(classify_reply), "classify_reply must stay synchronous"


# ── boundary: the Anthropic call lives in Rust, not Python ───────────────────

def test_no_anthropic_http_in_python_classifier():
    src = (BACKEND / "app" / "services" / "reply_classifier.py").read_text(encoding="utf-8")
    assert "api.anthropic.com" not in src, "the LLM call must NOT be in the Python classifier"
    assert "httpx" not in src, "no network client belongs in the request-path classifier"


def test_rust_ai_classify_handler_exists():
    # The muscle owns the LLM classification now — ChannelType + handler wired.
    models = (REPO / "backend-rust" / "src" / "models.rs").read_text(encoding="utf-8")
    transform = (REPO / "backend-rust" / "src" / "handlers" / "transform.rs").read_text(encoding="utf-8")
    moddisp = (REPO / "backend-rust" / "src" / "handlers" / "mod.rs").read_text(encoding="utf-8")
    assert 'rename = "ai_classify"' in models, "AiClassify ChannelType must exist"
    assert "pub async fn handle_ai_classify" in transform, "the Rust handler must exist"
    assert "AiClassify => transform::handle_ai_classify" in moddisp, "dispatch must route ai_classify"
    # opt-out can never be missed even on the LLM path (deterministic override).
    assert "force_unsubscribe" in transform


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
