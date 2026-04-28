"""
Claude API usage logger for outreach_automation.
Writes one row per API call to claude_usage_log in the shared DB.
"""
from __future__ import annotations

import logging
from typing import Any

from db import execute

log = logging.getLogger(__name__)

_PRICES: dict[str, dict[str, float]] = {
    "claude-sonnet-4-6": {
        "input": 3.00,
        "output": 15.00,
        "cache_read": 0.30,
        "cache_write": 3.75,
    },
    "claude-haiku-4-5-20251001": {
        "input": 0.80,
        "output": 4.00,
        "cache_read": 0.08,
        "cache_write": 1.00,
    },
}
_DEFAULT_PRICES = {"input": 3.00, "output": 15.00, "cache_read": 0.30, "cache_write": 3.75}


def _compute_cost(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
) -> float:
    p = _PRICES.get(model, _DEFAULT_PRICES)
    return (
        input_tokens * p["input"]
        + output_tokens * p["output"]
        + cache_read_tokens * p["cache_read"]
        + cache_write_tokens * p["cache_write"]
    ) / 1_000_000


def log_usage(
    *,
    call_type: str,
    model: str,
    response_data: dict[str, Any],
    campaign_id: str | None = None,
    lead_id: str | None = None,
) -> None:
    """Extract usage from Anthropic response dict and insert a log row."""
    usage = response_data.get("usage", {})
    input_tokens = usage.get("input_tokens", 0)
    output_tokens = usage.get("output_tokens", 0)
    cache_read_tokens = usage.get("cache_read_input_tokens", 0)
    cache_write_tokens = usage.get("cache_creation_input_tokens", 0)
    cost = _compute_cost(model, input_tokens, output_tokens, cache_read_tokens, cache_write_tokens)
    try:
        execute(
            """
            INSERT INTO claude_usage_log
                (service, call_type, model, input_tokens, output_tokens,
                 cache_read_tokens, cache_write_tokens, cost_usd, campaign_id, lead_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                "outreach", call_type, model,
                input_tokens, output_tokens,
                cache_read_tokens, cache_write_tokens,
                round(cost, 8),
                campaign_id, lead_id,
            ),
        )
    except Exception:
        log.warning("claude_usage: failed to log usage", exc_info=True)
