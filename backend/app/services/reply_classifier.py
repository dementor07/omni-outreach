"""B2 — reply intent classification (control-plane, synchronous, pure).

BOUNDARY (see rust-python-boundary-audit): the LLM call belongs in the muscle,
not in the FastAPI request worker. The Rust `ai.classify` handler
(handlers/transform.rs) now owns the Anthropic call. This module is the
synchronous, pure, no-I/O part that the inbound-reply webhook needs *inline*:

  - opt-out detection MUST be synchronous (a compliance guarantee can't wait for
    an async muscle round-trip), and it's deterministic anyway — no LLM needed;
  - the keyword heuristic gives an immediate, good-enough intent so
    `message.received` is emitted with a classification on the spot.

The nuanced LLM refinement (positive/question/objection) is dispatched to the
muscle's `ai.classify` channel as a follow-up when an event-driven reply node
exists; until then the keyword verdict stands. This removes the request-path
Anthropic call (the audit's 🔴 violation) with zero compliance regression.

Output intents: positive | question | objection | unsubscribe | neutral.
"""

from __future__ import annotations

from typing import Literal

Intent = Literal["positive", "question", "objection", "unsubscribe", "neutral"]
INTENTS: tuple[Intent, ...] = ("positive", "question", "objection", "unsubscribe", "neutral")

# Deterministic opt-out detection — ALWAYS applied so an unsubscribe is never
# missed. This is the compliance-critical path and is intentionally LLM-free.
_UNSUB_PATTERNS = (
    "unsubscribe", "opt out", "opt-out", "remove me", "stop emailing",
    "take me off", "do not contact", "don't contact", "no longer interested",
    "stop contacting",
)
_POSITIVE = ("interested", "let's talk", "lets talk", "book", "schedule", "call me", "sounds good", "tell me more", "sign up")
_OBJECTION = ("not interested", "no thanks", "not now", "wrong person", "already have", "too expensive", "not a fit")
_QUESTION = ("how much", "what is", "can you", "do you", "?", "pricing", "price")


def classify_reply(body: str) -> tuple[Intent, float, str, str]:
    """Pure, synchronous keyword classification. Returns
    (intent, confidence, reason, source). source is always "keyword" here; the
    "llm" source is produced by the Rust ai.classify handler on the muscle path.

    Opt-out wins first and unconditionally — the compliance guarantee."""
    text = (body or "").lower()
    if any(p in text for p in _UNSUB_PATTERNS):
        return "unsubscribe", 0.95, "opt-out keyword", "keyword"
    if any(p in text for p in _OBJECTION):
        return "objection", 0.6, "objection keyword", "keyword"
    if any(p in text for p in _POSITIVE):
        return "positive", 0.6, "positive keyword", "keyword"
    if any(p in text for p in _QUESTION):
        return "question", 0.55, "question keyword", "keyword"
    return "neutral", 0.4, "no signal", "keyword"
