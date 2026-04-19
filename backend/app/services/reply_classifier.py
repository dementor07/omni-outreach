"""Reply classification service — classify inbound replies as positive/negative/neutral/ooo/unsubscribe.

Uses keyword-based heuristics. Can be upgraded to LLM classification later.
"""
import re
from enum import Enum


class ReplyCategory(str, Enum):
    POSITIVE = "positive"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    OUT_OF_OFFICE = "out_of_office"
    UNSUBSCRIBE = "unsubscribe"
    BOUNCE = "bounce"


# Keyword patterns (case-insensitive)
_POSITIVE_PATTERNS = [
    r"\binterested\b", r"\blet'?s? (talk|chat|connect|meet|schedule|discuss)\b",
    r"\bsound[s]? (great|good|interesting)\b", r"\btell me more\b",
    r"\byes\b.*\bplease\b", r"\bi'?d? (like|love) to\b", r"\bset up a (call|meeting|time)\b",
    r"\bbook a (call|meeting|demo)\b", r"\bcalendar link\b", r"\bavailable\b.*\bnext week\b",
    r"\bhappy to\b", r"\bgood timing\b", r"\bgreat timing\b",
]

_NEGATIVE_PATTERNS = [
    r"\bnot interested\b", r"\bno thanks?\b", r"\bno thank you\b",
    r"\bplease (stop|remove|don'?t)\b", r"\bnot a (good|right) (fit|time)\b",
    r"\bwe'?re? (all )?set\b", r"\bpass\b", r"\bdon'?t (contact|email|message)\b",
    r"\bnot (looking|in the market)\b", r"\bwrong person\b",
]

_OOO_PATTERNS = [
    r"\bout of (the )?office\b", r"\bon (vacation|holiday|leave|pto)\b",
    r"\baway from\b.*\b(desk|office|email)\b", r"\blimited access\b",
    r"\breturn(ing)? on\b", r"\bauto.?reply\b", r"\bautomatic reply\b",
]

_UNSUBSCRIBE_PATTERNS = [
    r"\bunsubscribe\b", r"\bopt.?out\b", r"\bremove me\b",
    r"\bstop (emailing|messaging|contacting)\b", r"\btake me off\b",
]

_BOUNCE_PATTERNS = [
    r"\bmailer.?daemon\b", r"\bdelivery.*fail\b", r"\bundeliverable\b",
    r"\bmailbox.*full\b", r"\buser.*unknown\b", r"\baddress.*rejected\b",
    r"\b550\b.*\breject\b",
]


def _match_any(text: str, patterns: list[str]) -> bool:
    for pattern in patterns:
        if re.search(pattern, text, re.IGNORECASE):
            return True
    return False


def classify_reply(subject: str, body: str) -> tuple[ReplyCategory, float]:
    """Classify an inbound reply message.
    
    Returns:
        Tuple of (category, confidence) where confidence is 0.0-1.0.
    """
    text = f"{subject} {body}".strip()
    if not text:
        return ReplyCategory.NEUTRAL, 0.0

    # Check in priority order
    if _match_any(text, _BOUNCE_PATTERNS):
        return ReplyCategory.BOUNCE, 0.9

    if _match_any(text, _OOO_PATTERNS):
        return ReplyCategory.OUT_OF_OFFICE, 0.85

    if _match_any(text, _UNSUBSCRIBE_PATTERNS):
        return ReplyCategory.UNSUBSCRIBE, 0.9

    positive_hits = sum(1 for p in _POSITIVE_PATTERNS if re.search(p, text, re.IGNORECASE))
    negative_hits = sum(1 for p in _NEGATIVE_PATTERNS if re.search(p, text, re.IGNORECASE))

    if negative_hits > 0 and negative_hits >= positive_hits:
        confidence = min(0.6 + negative_hits * 0.1, 0.95)
        return ReplyCategory.NEGATIVE, confidence

    if positive_hits > 0:
        confidence = min(0.6 + positive_hits * 0.1, 0.95)
        return ReplyCategory.POSITIVE, confidence

    return ReplyCategory.NEUTRAL, 0.5


def get_suggested_action(category: ReplyCategory) -> str:
    """Get the recommended automation action for a reply category."""
    actions = {
        ReplyCategory.POSITIVE: "move_to_interested",
        ReplyCategory.NEGATIVE: "stop_sequence",
        ReplyCategory.NEUTRAL: "continue_sequence",
        ReplyCategory.OUT_OF_OFFICE: "pause_and_retry",
        ReplyCategory.UNSUBSCRIBE: "stop_and_blacklist",
        ReplyCategory.BOUNCE: "mark_bounced",
    }
    return actions.get(category, "continue_sequence")
