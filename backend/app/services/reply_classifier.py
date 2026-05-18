"""Reply classification service — classify inbound replies as positive/negative/neutral/ooo/unsubscribe.

Primary path: Claude Haiku LLM classification (matches the rest of the AI stack).
Fallback path: keyword-based heuristics (used when ANTHROPIC_API_KEY missing or LLM errors).

The vault and ARCHITECTURE_GAPS.md called out that this was keyword-only; it now
returns LLM verdicts when possible, with the regex layer kept as a safety net so
the canvas never blocks on an LLM outage.
"""

import json
import logging
import re
from enum import StrEnum

log = logging.getLogger(__name__)


class ReplyCategory(StrEnum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    OUT_OF_OFFICE = "out_of_office"
    UNSUBSCRIBE = "unsubscribe"
    BOUNCE = "bounce"


_VALID_CATEGORIES = {c.value for c in ReplyCategory}


_POSITIVE_PATTERNS = [
    r"\binterested\b",
    r"\blet'?s? (talk|chat|connect|meet|schedule|discuss)\b",
    r"\bsound[s]? (great|good|interesting)\b",
    r"\btell me more\b",
    r"\byes\b.*\bplease\b",
    r"\bi'?d? (like|love) to\b",
    r"\bset up a (call|meeting|time)\b",
    r"\bbook a (call|meeting|demo)\b",
    r"\bcalendar link\b",
    r"\bavailable\b.*\bnext week\b",
    r"\bhappy to\b",
    r"\bgood timing\b",
    r"\bgreat timing\b",
]

_NEGATIVE_PATTERNS = [
    r"\bnot interested\b",
    r"\bno thanks?\b",
    r"\bno thank you\b",
    r"\bplease (stop|remove|don'?t)\b",
    r"\bnot a (good|right) (fit|time)\b",
    r"\bwe'?re? (all )?set\b",
    r"\bpass\b",
    r"\bdon'?t (contact|email|message)\b",
    r"\bnot (looking|in the market)\b",
    r"\bwrong person\b",
]

_OOO_PATTERNS = [
    r"\bout of (the )?office\b",
    r"\bon (vacation|holiday|leave|pto)\b",
    r"\baway from\b.*\b(desk|office|email)\b",
    r"\blimited access\b",
    r"\breturn(ing)? on\b",
    r"\bauto.?reply\b",
    r"\bautomatic reply\b",
]

_UNSUBSCRIBE_PATTERNS = [
    r"\bunsubscribe\b",
    r"\bopt.?out\b",
    r"\bremove me\b",
    r"\bstop (emailing|messaging|contacting)\b",
    r"\btake me off\b",
]

_BOUNCE_PATTERNS = [
    r"\bmailer.?daemon\b",
    r"\bdelivery.*fail\b",
    r"\bundeliverable\b",
    r"\bmailbox.*full\b",
    r"\buser.*unknown\b",
    r"\baddress.*rejected\b",
    r"\b550\b.*\breject\b",
]


def _match_any(text: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def _keyword_classify(subject: str, body: str) -> tuple[ReplyCategory, float]:
    text = f"{subject} {body}".strip()
    if not text:
        return ReplyCategory.NEUTRAL, 0.0

    if _match_any(text, _BOUNCE_PATTERNS):
        return ReplyCategory.BOUNCE, 0.9
    if _match_any(text, _OOO_PATTERNS):
        return ReplyCategory.OUT_OF_OFFICE, 0.85
    if _match_any(text, _UNSUBSCRIBE_PATTERNS):
        return ReplyCategory.UNSUBSCRIBE, 0.9

    positive_hits = sum(1 for p in _POSITIVE_PATTERNS if re.search(p, text, re.IGNORECASE))
    negative_hits = sum(1 for p in _NEGATIVE_PATTERNS if re.search(p, text, re.IGNORECASE))

    if negative_hits > 0 and negative_hits >= positive_hits:
        return ReplyCategory.NEGATIVE, min(0.6 + negative_hits * 0.1, 0.95)
    if positive_hits > 0:
        return ReplyCategory.POSITIVE, min(0.6 + positive_hits * 0.1, 0.95)
    return ReplyCategory.NEUTRAL, 0.5


_SYSTEM = (
    "You classify inbound replies to B2B outreach messages. "
    "Output a single JSON object with exactly two keys: "
    '{"category": one of [positive, negative, neutral, out_of_office, unsubscribe, bounce], '
    '"confidence": float 0.0-1.0}. '
    "No prose, no preamble, no markdown — JSON only. "
    "Categories: positive = wants to engage, asks for info, books time. "
    "negative = declines, asks to stop. neutral = ambiguous, off-topic. "
    "out_of_office = auto-reply for absence. unsubscribe = explicit opt-out. "
    "bounce = delivery failure auto-reply."
)


async def _llm_classify(subject: str, body: str) -> tuple[ReplyCategory, float] | None:
    """Return None on any error so the caller can fall back to keywords."""
    try:
        from app.config import settings
        if not getattr(settings, "anthropic_api_key", None):
            return None
        from app.services.screener import DEFAULT_MODEL, _get_client

        prompt = f"Subject: {subject or '(no subject)'}\n\nBody:\n{body or '(empty)'}"
        resp = await _get_client().messages.create(
            model=DEFAULT_MODEL,
            max_tokens=80,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = resp.content[0].text.strip()
        # Tolerate accidental fenced output.
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)
        cat = str(parsed.get("category", "")).strip().lower()
        if cat not in _VALID_CATEGORIES:
            return None
        try:
            conf = float(parsed.get("confidence", 0.7))
        except (TypeError, ValueError):
            conf = 0.7
        conf = max(0.0, min(1.0, conf))
        return ReplyCategory(cat), conf
    except Exception as e:  # noqa: BLE001 — fall back to keyword classifier
        log.warning(f"[reply_classifier] LLM classification failed; falling back to keywords: {e}")
        return None


async def classify_reply_async(subject: str, body: str) -> tuple[ReplyCategory, float]:
    """Async LLM-first classifier. Falls back to keyword regex on any error."""
    verdict = await _llm_classify(subject, body)
    if verdict is not None:
        return verdict
    return _keyword_classify(subject, body)


def classify_reply(subject: str, body: str) -> tuple[ReplyCategory, float]:
    """Sync keyword-only classifier — preserved for callers that can't await
    (webhook hot paths inside sync code). Prefer ``classify_reply_async``."""
    return _keyword_classify(subject, body)


def get_suggested_action(category: ReplyCategory) -> str:
    actions = {
        ReplyCategory.POSITIVE: "move_to_interested",
        ReplyCategory.NEGATIVE: "stop_sequence",
        ReplyCategory.NEUTRAL: "continue_sequence",
        ReplyCategory.OUT_OF_OFFICE: "pause_and_retry",
        ReplyCategory.UNSUBSCRIBE: "stop_and_blacklist",
        ReplyCategory.BOUNCE: "mark_bounced",
    }
    return actions.get(category, "continue_sequence")
