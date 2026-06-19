"""AI job execution — the model calls behind ad-hoc AI Studio jobs.

BOUNDARY (rust-python-boundary-audit): like ``reply_drafter`` (the inbox
suggest-reply), these are OPERATOR-TRIGGERED, bounded AI calls — the operator
clicks "Run scoring" in AI Studio and a worker scores the workspace's leads.
They are NOT the per-lead, per-send hot path (that is the muscle's job, e.g.
``ai_compose``/``ai_screen`` inside a running campaign). Routing ad-hoc Studio
jobs through the muscle would mean inventing synthetic leads/nodes (the SPINE-2
black hole) and reverse-engineering the result→fact bridge for a non-advancing
job — fighting the sequence architecture, not fitting it. So ad-hoc jobs run in
a dedicated worker (``ai_jobs_worker``) using this module, on the same direct
Anthropic call pattern ``reply_drafter`` established.

Each function FAILS CLOSED with a clear error (no anthropic connection → the job
is marked failed with a useful message) rather than silently degrading — an
operator who clicked "score my leads" must know if it didn't happen.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.db import fetch_one, system_scope
from app.services.encryption import decrypt

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


class AiJobError(RuntimeError):
    """Raised when a job cannot run (missing credential, bad model response)."""


async def anthropic_key(workspace_id: str) -> str | None:
    """Decrypt the workspace's anthropic connection api_key, or None.

    Mirrors reply_drafter._anthropic_key — most-recent anthropic connection.
    Wrapped in system_scope() because callers are background workers with no
    request context; db.acquire() refuses an unscoped connection (RLS guard)."""
    async with system_scope():
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


async def _anthropic_text(api_key: str, system: str, user: str, max_tokens: int) -> str:
    """One bounded Anthropic Messages call → the text content. Raises AiJobError."""
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": DEFAULT_MODEL,
                    "max_tokens": max_tokens,
                    "system": system,
                    "messages": [{"role": "user", "content": user}],
                },
            )
    except httpx.HTTPError as e:
        raise AiJobError(f"anthropic network error: {e}") from e
    if resp.status_code != 200:
        raise AiJobError(f"anthropic HTTP {resp.status_code}")
    try:
        return (resp.json()["content"][0]["text"] or "").strip()
    except (KeyError, IndexError, ValueError) as e:
        raise AiJobError("anthropic returned an unexpected response shape") from e


def _extract_json(text: str) -> dict[str, Any] | None:
    """Pull the first {...} object out of a model response (may be fenced)."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


# ── Scoring ──────────────────────────────────────────────────────────────────

_SCORE_SYSTEM = (
    "You are a B2B lead-scoring engine. Given an ICP (ideal customer profile) and "
    "a lead's facts, rate how well the lead fits the ICP from 0 (no fit) to 100 "
    "(perfect fit). Respond with ONLY a compact JSON object: "
    '{"score": <int 0-100>, "reasons": ["<short reason>", ...]}. '
    "Give 2-4 concise reasons grounded in the lead's facts. Do not invent facts."
)


async def score_lead(api_key: str, icp: str, lead_facts: dict[str, Any]) -> dict[str, Any]:
    """Score one lead against the ICP. Returns {score:int, reasons:list[str], model:str}."""
    user = (
        f"ICP:\n{icp}\n\n"
        f"Lead facts:\n{json.dumps(lead_facts, separators=(',', ':'), default=str)}"
    )
    text = await _anthropic_text(api_key, _SCORE_SYSTEM, user, 400)
    parsed = _extract_json(text)
    if not parsed or "score" not in parsed:
        raise AiJobError("score response was not valid JSON with a score")
    try:
        score = int(parsed["score"])
    except (TypeError, ValueError) as e:
        raise AiJobError("score was not an integer") from e
    score = max(0, min(100, score))
    reasons = parsed.get("reasons") or []
    if not isinstance(reasons, list):
        reasons = [str(reasons)]
    return {"score": score, "reasons": [str(r)[:300] for r in reasons][:6], "model": DEFAULT_MODEL}


# ── Compose ──────────────────────────────────────────────────────────────────

_COMPOSE_SYSTEM = (
    "You write {tone} outbound {channel} messages for B2B outreach. Output is the "
    "message body only — no subject line, no signature, no preamble. Keep it under "
    "{max_words} words. Reference the lead's facts only if present and relevant."
)


async def compose_message(
    api_key: str,
    instruction: str,
    lead_facts: dict[str, Any],
    *,
    channel: str = "email",
    tone: str = "professional",
    max_words: int = 120,
) -> dict[str, Any]:
    """Draft a per-lead outreach message. Returns {draft:str, model:str}."""
    system = _COMPOSE_SYSTEM.format(tone=tone, channel=channel, max_words=max_words)
    user = (
        f"Operator instructions:\n{instruction}\n\n"
        f"Lead facts:\n{json.dumps(lead_facts, separators=(',', ':'), default=str)}"
    )
    text = await _anthropic_text(api_key, system, user, max_words * 8)
    if not text:
        raise AiJobError("compose returned an empty draft")
    return {"draft": text[:4000], "model": DEFAULT_MODEL}


# ── Classify ──────────────────────────────────────────────────────────────────

_INTENTS = ("positive", "question", "objection", "unsubscribe", "neutral")
_CLASSIFY_SYSTEM = (
    "Classify the INTENT of a reply to a sales/outreach message. Respond with ONLY "
    'a compact JSON object: {"intent": one of '
    '["positive","question","objection","unsubscribe","neutral"], '
    '"confidence": 0.0-1.0, "reason": "<=120 chars"}. '
    "positive=interested/wants to talk; question=asking for info; "
    "objection=pushback/not now/wrong person; unsubscribe=opt-out/stop; "
    "neutral=auto-reply/OOO/other."
)


async def classify_reply(api_key: str, body: str) -> dict[str, Any]:
    """Classify one reply's intent. Returns {intent, confidence, reason, model}."""
    truncated = body[:4000]
    text = await _anthropic_text(api_key, _CLASSIFY_SYSTEM, truncated, 200)
    parsed = _extract_json(text)
    intent = (parsed or {}).get("intent")
    if intent not in _INTENTS:
        raise AiJobError("classify response had no valid intent")
    try:
        confidence = max(0.0, min(1.0, float((parsed or {}).get("confidence", 0.5))))
    except (TypeError, ValueError):
        confidence = 0.5
    reason = str((parsed or {}).get("reason", ""))[:200]
    return {"intent": intent, "confidence": confidence, "reason": reason, "model": DEFAULT_MODEL}
