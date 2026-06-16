"""B2 — reply intent classification.

Industry-pro pattern (researched 2026-06-16; LangChain agents-from-scratch +
production write-ups): a single, bounded, schema-constrained LLM call embedded
in the existing dataflow, FAIL-OPEN to a deterministic keyword heuristic, with
provenance tracked (`source` = "llm" | "keyword"). NOT a multi-agent/LangGraph
orchestration — we already own the orchestration spine; adding a framework for
one classification step is the over-engineering the sources warn against.

Output intents (what the reply→wake-up routing + suppression key on):
  positive    — interested / wants to talk / books time
  question    — asking for info, not yet committed
  objection    — pushback / not now / wrong person
  unsubscribe — opt-out / stop / remove me  (also auto-suppresses, T1)
  neutral     — auto-reply, OOO, anything else

`classify_reply` decrypts the workspace's `anthropic` connection and makes ONE
Haiku call; any failure (no connection, timeout, malformed) falls back to
keyword rules. Unsubscribe keywords are ALWAYS caught deterministically even
when the LLM path is used, so opt-outs can never be missed.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Literal

import httpx

from app.db import fetch_one
from app.services.encryption import decrypt

log = logging.getLogger(__name__)

Intent = Literal["positive", "question", "objection", "unsubscribe", "neutral"]
INTENTS: tuple[Intent, ...] = ("positive", "question", "objection", "unsubscribe", "neutral")

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"

# Deterministic opt-out detection — ALWAYS applied first so an unsubscribe is
# never missed regardless of the LLM path.
_UNSUB_PATTERNS = (
    "unsubscribe", "opt out", "opt-out", "remove me", "stop emailing",
    "take me off", "do not contact", "don't contact", "no longer interested",
    "stop contacting",
)
_POSITIVE = ("interested", "let's talk", "lets talk", "book", "schedule", "call me", "sounds good", "tell me more", "sign up")
_OBJECTION = ("not interested", "no thanks", "not now", "wrong person", "already have", "too expensive", "not a fit")
_QUESTION = ("how much", "what is", "can you", "do you", "?", "pricing", "price")


def _keyword_classify(body: str) -> tuple[Intent, float]:
    """Deterministic fallback. Returns (intent, confidence)."""
    text = (body or "").lower()
    if any(p in text for p in _UNSUB_PATTERNS):
        return "unsubscribe", 0.95
    if any(p in text for p in _OBJECTION):
        return "objection", 0.6
    if any(p in text for p in _POSITIVE):
        return "positive", 0.6
    if any(p in text for p in _QUESTION):
        return "question", 0.55
    return "neutral", 0.4


def _force_unsubscribe(body: str) -> bool:
    text = (body or "").lower()
    return any(p in text for p in _UNSUB_PATTERNS)


async def _anthropic_key(workspace_id: str) -> str | None:
    row = await fetch_one(
        "SELECT credentials_encrypted FROM omni_connections "
        "WHERE workspace_id=$1 AND provider='anthropic' "
        "ORDER BY connected_at DESC LIMIT 1",
        workspace_id,
    )
    if not row:
        return None
    try:
        bundle = json.loads(decrypt(row["credentials_encrypted"]))
    except Exception:  # noqa: BLE001
        return None
    return bundle.get("api_key") or bundle.get("apiKey")


_PROMPT = (
    "Classify the INTENT of this reply to a sales/outreach message. "
    "Respond with ONLY a compact JSON object: "
    '{"intent": one of ["positive","question","objection","unsubscribe","neutral"], '
    '"confidence": 0.0-1.0, "reason": "<=120 chars}. '
    "positive=interested/wants to talk; question=asking for info; "
    "objection=pushback/not now/wrong person; unsubscribe=opt-out/stop; "
    "neutral=auto-reply/OOO/other. Reply body:\n\n"
)


async def classify_reply(
    workspace_id: str, body: str
) -> tuple[Intent, float, str, str]:
    """Returns (intent, confidence, reason, source). source ∈ {llm, keyword}.

    Fail-open: any LLM problem degrades to the keyword heuristic. An
    unsubscribe keyword always wins regardless of the LLM verdict."""
    api_key = await _anthropic_key(workspace_id)
    if not api_key:
        intent, conf = _keyword_classify(body)
        return intent, conf, "no anthropic connection", "keyword"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": DEFAULT_MODEL,
                    "max_tokens": 200,
                    "messages": [{"role": "user", "content": _PROMPT + (body or "")[:4000]}],
                },
            )
        if resp.status_code != 200:
            raise RuntimeError(f"anthropic HTTP {resp.status_code}")
        text = resp.json()["content"][0]["text"]
        # The model may wrap JSON in prose/fences — extract the object.
        match = re.search(r"\{.*\}", text, re.DOTALL)
        data = json.loads(match.group(0) if match else text)
        intent = data.get("intent")
        if intent not in INTENTS:
            raise ValueError(f"bad intent {intent!r}")
        confidence = max(0.0, min(1.0, float(data.get("confidence", 0.5))))
        reason = str(data.get("reason", ""))[:200]
        # Deterministic opt-out override — never miss an unsubscribe.
        if _force_unsubscribe(body) and intent != "unsubscribe":
            return "unsubscribe", 0.95, "keyword opt-out override", "llm"
        return intent, confidence, reason, "llm"
    except Exception as e:  # noqa: BLE001
        log.warning("reply classify fell back to keyword: %s", e)
        intent, conf = _keyword_classify(body)
        return intent, conf, f"llm fallback: {e}", "keyword"
