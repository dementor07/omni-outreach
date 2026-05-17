"""LLM service. Single module for every Claude call.

Three public functions:
- screen_lead: ACCEPT/REJECT classifier for condition_ai_screen
- get_llm_response: free-form completion used by action_data_transform
- generate_message: per-lead message composition for action_ai_compose

Model defaults to Haiku 4.5 (claude-haiku-4-5-20251001), the current latest.
"""

import logging

import anthropic

from app.config import settings

log = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None

DEFAULT_MODEL = "claude-haiku-4-5-20251001"


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def screen_lead(headline: str, screening_prompt: str) -> str:
    """Returns 'ACCEPT' or 'REJECT'. Defaults to REJECT on any error."""
    try:
        resp = await _get_client().messages.create(
            model=DEFAULT_MODEL,
            max_tokens=10,
            system="You are a lead screening assistant. Respond with exactly one word: ACCEPT or REJECT.",
            messages=[{"role": "user", "content": f"{screening_prompt}\n\nLead headline: {headline}"}],
        )
        decision = resp.content[0].text.strip().upper()
        return "ACCEPT" if decision == "ACCEPT" else "REJECT"
    except Exception as e:
        log.warning(f"[screener] Error screening headline '{headline}': {e}")
        return "REJECT"


async def get_llm_response(prompt: str, *, max_tokens: int = 200, system: str | None = None) -> str:
    """Free-form single-turn completion. Returns the model's text or '' on error.

    Used by action_data_transform to derive `extra_data` values per lead.
    """
    try:
        resp = await _get_client().messages.create(
            model=DEFAULT_MODEL,
            max_tokens=max_tokens,
            system=system or "Respond concisely. Output the answer only — no preamble, no quotes, no explanation.",
            messages=[{"role": "user", "content": prompt}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log.warning(f"[llm] get_llm_response failed: {e}")
        return ""


async def generate_message(
    *,
    instruction: str,
    lead: dict,
    channel: str,
    tone: str = "professional",
    max_words: int = 120,
) -> str:
    """Compose a per-lead outbound message. Returns plain text body.

    `instruction` is the operator's prompt ("Cold opener referencing their recent post about X").
    Lead facts are passed as a compact JSON block so the model can ground the message.
    """
    facts = {
        k: v
        for k, v in {
            "first_name": lead.get("first_name"),
            "last_name": lead.get("last_name"),
            "headline": lead.get("headline"),
            "company": lead.get("company"),
            "location": lead.get("location"),
            "source": lead.get("source"),
        }.items()
        if v
    }
    extra = lead.get("extra_data") or {}
    if isinstance(extra, dict):
        for k, v in extra.items():
            if v and k not in facts:
                facts[k] = v

    system = (
        f"You write {tone} outbound {channel} messages for B2B outreach. "
        f"Output is the message body only — no subject lines, no signatures, no preamble. "
        f"Keep it under {max_words} words. Reference the lead's facts only if they are present and relevant. "
        f"If a referenced field is missing, omit that sentence rather than invent."
    )

    import json as _json

    user = (
        f"Operator instructions:\n{instruction}\n\n"
        f"Lead facts (only use what's present):\n{_json.dumps(facts, ensure_ascii=False)}"
    )

    try:
        resp = await _get_client().messages.create(
            model=DEFAULT_MODEL,
            max_tokens=max(256, max_words * 8),
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return resp.content[0].text.strip()
    except Exception as e:
        log.warning(f"[llm] generate_message failed: {e}")
        raise
