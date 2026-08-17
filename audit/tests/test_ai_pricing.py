"""AI-COST-001 — the cost calculator must be EXACT, not estimated.

Locks the per-model rates and the arithmetic so a pricing drift (or a fat-fingered
rate) can never silently mis-bill the ledger. Costs below are hand-computed from
the first-party Anthropic rates (per 1M tokens):
  Haiku 4.5  $1 / $5      Sonnet 5  $3 / $15      Opus 5  $5 / $25      Fable 5  $10 / $50
"""

from decimal import Decimal

import pytest

from app.services import ai_pricing


@pytest.mark.parametrize(
    "model,inp,out,expected",
    [
        # one real Haiku screen call: ~700 in, ~150 out → (700*1 + 150*5)/1e6
        ("claude-haiku-4-5", 700, 150, "0.001450"),
        ("claude-haiku-4-5-20251001", 700, 150, "0.001450"),
        # sonnet compose: (1000*3 + 200*15)/1e6
        ("claude-sonnet-5", 1000, 200, "0.006000"),
        # opus: (1000*5 + 500*25)/1e6
        ("claude-opus-5", 1000, 500, "0.017500"),
        # fable: (100*10 + 50*50)/1e6
        ("claude-fable-5", 100, 50, "0.003500"),
        # zero tokens → zero cost
        ("claude-haiku-4-5", 0, 0, "0.000000"),
    ],
)
def test_cost_is_exact(model, inp, out, expected):
    assert ai_pricing.cost_usd(model, inp, out) == Decimal(expected)


def test_unknown_model_priced_at_top_tier_never_undercounts():
    # unknown model → Fable-tier ($10/$50), so an untracked model is never under-billed
    assert ai_pricing.cost_usd("some-future-model", 100, 0) == Decimal("0.001000")
    assert ai_pricing.cost_usd("some-future-model", 100, 0) == ai_pricing.cost_usd("claude-fable-5", 100, 0)


def test_cache_tokens_priced_read_tenth_write_1_25x():
    # cache-read = 0.1x input; 1000 Haiku cache-read tokens → 1000*1*0.1/1e6
    assert ai_pricing.cost_usd("claude-haiku-4-5", 0, 0, cache_read_tokens=1000) == Decimal("0.000100")
    # cache-write (creation) = 1.25x input; 1000 Haiku → 1000*1*1.25/1e6
    assert ai_pricing.cost_usd("claude-haiku-4-5", 0, 0, cache_creation_tokens=1000) == Decimal("0.001250")


def test_usage_from_response_reads_real_token_fields():
    body = {
        "content": [{"type": "text", "text": "ok"}],
        "usage": {
            "input_tokens": 712,
            "output_tokens": 143,
            "cache_read_input_tokens": 50,
            "cache_creation_input_tokens": 0,
        },
    }
    u = ai_pricing.usage_from_response(body)
    assert u == {"input_tokens": 712, "output_tokens": 143, "cache_read_tokens": 50, "cache_creation_tokens": 0}


def test_usage_from_response_tolerates_missing_usage():
    assert ai_pricing.usage_from_response({}) == {
        "input_tokens": 0, "output_tokens": 0, "cache_read_tokens": 0, "cache_creation_tokens": 0,
    }
    assert ai_pricing.usage_from_response(None)["input_tokens"] == 0


@pytest.mark.parametrize(
    "spend,cap,mode,blocks",
    [
        # alert never blocks, even far over the cap
        ("100", "10", ai_pricing.MODE_ALERT, False),
        # warn_stop and hard_stop both hard-stop once spend reaches the cap
        ("10", "10", ai_pricing.MODE_WARN_STOP, True),
        ("9.99", "10", ai_pricing.MODE_WARN_STOP, False),
        ("10.01", "10", ai_pricing.MODE_HARD_STOP, True),
        ("5", "10", ai_pricing.MODE_HARD_STOP, False),
        # NULL mode defaults to warn_stop (blocks at cap)
        ("10", "10", None, True),
    ],
)
def test_guard_block_semantics(spend, cap, mode, blocks):
    assert ai_pricing._blocks(spend, cap, mode) is blocks
