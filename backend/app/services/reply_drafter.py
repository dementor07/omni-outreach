"""B3 — AI-suggested reply draft for the inbox.

BOUNDARY (rust-python-boundary-audit): this is the PREVIEW class, like
`naukri_preview` — an explicit, user-triggered, single, synchronous call: the
operator clicks "suggest" and waits for one draft string. It is NOT volume or
per-entity hot-path work, so it stays in Python; routing it through the async
muscle would mean holding the HTTP request open polling Kafka for the result —
strictly worse UX for zero throughput gain. (The automated, per-reply classifier
WAS hot-path and was moved off the request path; this interactive single-shot
draft is the documented exemption.)

One bounded Anthropic Haiku call given the recent thread context + the inbound
message's classified intent; FAIL-OPEN to a short intent-shaped template so the
compose box is never empty. The operator always edits before sending.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from app.db import fetch_one
from app.services.encryption import decrypt

log = logging.getLogger(__name__)

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"


async def _anthropic_key(workspace_id: str) -> str | None:
    """Decrypt the workspace's anthropic connection api_key, or None."""
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
