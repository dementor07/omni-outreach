"""Render a message-tone preset into an Anthropic system-prompt fragment.

TONE-PRESET-001. A tone preset (omni_message_tones.spec — the structured JSON the
team authored: personality_traits, word_count rules, opening_styles,
value_delivery, closing_approaches, avoid lists, anti-pitch/cta/credibility
rules, …) is a prompt-engineering asset. This module turns one into the `system`
string the Rust muscle hands Anthropic for ai.compose.

It is PURE and I/O-free: the dispatcher (which has the DB) loads the preset row
and calls ``build_tone_system_prompt(spec, channel)``; the muscle just uses the
returned string. Keeping it pure lets us lock every tone's rendering in unit
tests without a DB or an LLM, and means a malformed preset degrades gracefully
(missing keys are simply skipped) rather than wedging a send.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

_MAX_ITEMS = 8  # cap each list so the prompt stays focused, not a wall of text


def _items(value: Any) -> list[str]:
    """Coerce a spec field into a clean list of short strings."""
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Sequence):
        out: list[str] = []
        for v in value:
            if isinstance(v, str) and v.strip():
                out.append(v.strip())
            elif isinstance(v, Mapping):
                # follow-up strategy objects: {approach, description, techniques}
                desc = str(v.get("description") or v.get("approach") or "").strip()
                if desc:
                    out.append(desc)
        return out
    return []


def _bullets(label: str, value: Any) -> str | None:
    rows = _items(value)[:_MAX_ITEMS]
    if not rows:
        return None
    body = "\n".join(f"- {r}" for r in rows)
    return f"{label}:\n{body}"


def word_count_bounds(spec: Mapping[str, Any], fallback: int = 120) -> tuple[int, int]:
    """The (recommended, max) word counts for a tone — used both in the prompt
    and to size the model's max_tokens. Falls back sanely when absent."""
    wc = spec.get("word_count") if isinstance(spec.get("word_count"), Mapping) else {}
    recommended = int(wc.get("recommended") or wc.get("max") or fallback)
    maximum = int(wc.get("max") or recommended or fallback)
    return recommended, maximum


def build_tone_system_prompt(spec: Mapping[str, Any], channel: str = "email") -> str:
    """Render the preset into a single system-prompt string. Sections present in
    the spec are included; absent ones are skipped (graceful degradation)."""
    tone_name = str(spec.get("tone") or "professional")
    description = str(spec.get("description") or "")
    recommended, maximum = word_count_bounds(spec)

    head = (
        f"You write outbound {channel} messages for B2B outreach in the "
        f"\"{tone_name}\" tone."
    )
    if description:
        head += f" {description}"

    sections: list[str] = [head]

    length = (
        f"Length: aim for about {recommended} words, never exceed {maximum}. "
        "Output the message body ONLY. No subject line, no signature, no preamble, "
        "no surrounding quotes. Never use em dashes or en dashes anywhere in the "
        "output, use periods and commas instead."
    )
    wc = spec.get("word_count") if isinstance(spec.get("word_count"), Mapping) else {}
    if wc.get("rationale"):
        length += f" ({wc['rationale']})"
    sections.append(length)

    # The instruction-bearing sections, in the order they shape a draft.
    for label, key in (
        ("Voice & personality", "personality_traits"),
        ("How to open", "opening_styles"),
        ("Trigger rules", "trigger_quality_rules"),
        ("Delivering value", "value_delivery"),
        ("Credibility", "credibility_rules"),
        ("How to close", "closing_approaches"),
        ("Call to action", "cta_rules"),
        ("Personalise using", "personalization_hooks"),
    ):
        block = _bullets(label, spec.get(key))
        if block:
            sections.append(block)

    # Hard prohibitions last so they're the most recent instruction the model sees.
    prohibitions: list[str] = []
    prohibitions += _items(spec.get("avoid"))
    prohibitions += _items(spec.get("anti_pitch_rules"))
    if prohibitions:
        body = "\n".join(f"- {r}" for r in prohibitions[: _MAX_ITEMS * 2])
        sections.append(f"NEVER do the following:\n{body}")

    return "\n\n".join(sections)
