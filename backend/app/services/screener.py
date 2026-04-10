import logging

import anthropic

from app.config import settings

log = logging.getLogger(__name__)

_client: anthropic.AsyncAnthropic | None = None


def _get_client() -> anthropic.AsyncAnthropic:
    global _client
    if _client is None:
        _client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    return _client


async def screen_lead(headline: str, screening_prompt: str) -> str:
    """Returns 'ACCEPT' or 'REJECT'. Defaults to REJECT on any error."""
    try:
        resp = await _get_client().messages.create(
            model="claude-haiku-20240307",
            max_tokens=10,
            system="You are a lead screening assistant. Respond with exactly one word: ACCEPT or REJECT.",
            messages=[
                {"role": "user", "content": f"{screening_prompt}\n\nLead headline: {headline}"}
            ],
        )
        decision = resp.content[0].text.strip().upper()
        return "ACCEPT" if decision == "ACCEPT" else "REJECT"
    except Exception as e:
        log.warning(f"[screener] Error screening headline '{headline}': {e}")
        return "REJECT"
