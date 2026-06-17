"""B3 — AI-suggested reply draft for the inbox.

Same industry-pro shape as `reply_classifier` (researched 2026-06-16): a single,
bounded, schema-light LLM call (Anthropic Haiku) embedded in the request path,
FAIL-OPEN to a deterministic templated draft, with provenance (`source` =
"llm" | "template"). The operator always edits before sending — this only
removes the blank-page problem, it is never an auto-send.

`suggest_reply` decrypts the workspace's `anthropic` connection and makes ONE
Haiku call given the recent thread context + the inbound message's classified
intent; any failure (no connection, timeout, malformed) falls back to a
short intent-shaped template so the compose box is never empty.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.services.reply_classifier import (
    ANTHROPIC_URL,
    ANTHROPIC_VERSION,
    DEFAULT_MODEL,
    _anthropic_key,
)

log = logging.getLogger(__name__)

# Deterministic fallback drafts — keyed by the inbound reply's classified
# intent so the suggestion is at least intent-appropriate when the LLM path is
# unavailable. Kept short; the operator edits before sending.
_TEMPLATES: dict[str, str] = {
    "positive": (
        "Great to hear from you! Happy to set up a quick call to walk you "
        "through the details — does later this week work?"
    ),
    "question": (
        "Thanks for the question — happy to clarify. Could you let me know a "
        "bit more about what you're looking to solve so I can point you to the "
        "right answer?"
    ),
    "objection": (
        "Completely understand, and I appreciate you letting me know. If "
        "anything changes or it'd help to revisit down the line, I'm here."
    ),
    "neutral": "Thanks for getting back to me — let me know if there's anything I can help with.",
}
_DEFAULT_TEMPLATE = _TEMPLATES["neutral"]


def _template_for(intent: str | None) -> str:
    return _TEMPLATES.get(intent or "", _DEFAULT_TEMPLATE)


def _transcript(messages: list[dict[str, Any]], limit: int = 8) -> str:
    """Render the last `limit` messages as a plain Sender: body transcript."""
    recent = messages[-limit:]
    lines: list[str] = []
    for m in recent:
        who = "Us" if m.get("direction") == "outbound" else "Them"
        body = (m.get("body") or "").strip().replace("\n", " ")
        if body:
            lines.append(f"{who}: {body[:500]}")
    return "\n".join(lines)


_PROMPT = (
    "You are drafting a short, professional reply on behalf of a sales/outreach "
    "rep. Write ONLY the reply body — no subject line, no greeting placeholder "
    "like [Name], no signature, no quotes around it. Keep it under 80 words, "
    "warm and concise, and move the conversation forward. The latest inbound "
    "message was classified as intent='{intent}'.\n\nConversation so far:\n{transcript}\n\n"
    "Reply:"
)


async def suggest_reply(
    workspace_id: str,
    messages: list[dict[str, Any]],
    intent: str | None = None,
) -> tuple[str, str]:
    """Returns (draft, source). source ∈ {llm, template}.

    Fail-open: any LLM problem degrades to an intent-shaped template so the
    compose box always has a usable starting point."""
    api_key = await _anthropic_key(workspace_id)
    if not api_key:
        return _template_for(intent), "template"

    transcript = _transcript(messages)
    prompt = _PROMPT.format(intent=intent or "neutral", transcript=transcript or "(no prior messages)")
    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            resp = await client.post(
                ANTHROPIC_URL,
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": DEFAULT_MODEL,
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
        if resp.status_code != 200:
            raise RuntimeError(f"anthropic HTTP {resp.status_code}")
        text = (resp.json()["content"][0]["text"] or "").strip()
        if not text:
            raise ValueError("empty draft")
        return text[:2000], "llm"
    except Exception as e:  # noqa: BLE001
        log.warning("reply draft fell back to template: %s", e)
        return _template_for(intent), "template"
