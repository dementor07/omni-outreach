"""AI-COST-001 — the single source of truth for pricing + bounding Anthropic spend.

Every model call (the muscle's per-lead screen/compose, and ad-hoc Studio jobs)
reports the REAL token counts from the API response; this module turns those into
an exact ``cost_usd``, records one ``omni_ai_usage`` row, and advances the running
totals the dispatch guard reads. Pricing lives HERE only — the Rust muscle reports
raw token counts, Python prices them, so rates are never duplicated or drift.

Rates are per 1,000,000 tokens, first-party Anthropic API (claude-api skill,
cached 2026-06-24). Cache-read is ~0.1x input, cache-write (5-min TTL) ~1.25x.
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from app.db import execute, fetch_one, system_scope

log = logging.getLogger(__name__)

# model id -> (input $/1M, output $/1M). Alias + date-suffixed forms both map.
_RATES: dict[str, tuple[str, str]] = {
    "claude-haiku-4-5": ("1.00", "5.00"),
    "claude-haiku-4-5-20251001": ("1.00", "5.00"),
    "claude-sonnet-5": ("3.00", "15.00"),
    "claude-sonnet-4-6": ("3.00", "15.00"),
    "claude-opus-5": ("5.00", "25.00"),
    "claude-opus-4-8": ("5.00", "25.00"),
    "claude-opus-4-7": ("5.00", "25.00"),
    "claude-opus-4-6": ("5.00", "25.00"),
    "claude-fable-5": ("10.00", "50.00"),
}
# Unknown model → price at the most expensive known tier so an untracked model is
# never UNDER-counted (a conservative estimate beats a silent gap in the ledger).
_FALLBACK = ("10.00", "50.00")
_MILLION = Decimal(1_000_000)

# Guard modes (stored on omni_workflows.ai_budget_mode / omni_ai_workspace_budget.mode).
MODE_ALERT = "alert"          # never blocks; the panel just shows the bar filling
MODE_WARN_STOP = "warn_stop"  # warn at 80% (panel), hard-stop at 100%
MODE_HARD_STOP = "hard_stop"  # hard-stop at 100%
DEFAULT_MODE = MODE_WARN_STOP
WARN_FRACTION = Decimal("0.8")


def _rates(model: str) -> tuple[Decimal, Decimal]:
    inp, out = _RATES.get(model or "", _FALLBACK)
    return Decimal(inp), Decimal(out)


def cost_usd(
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_creation_tokens: int = 0,
) -> Decimal:
    """Exact cost of one call. Cache-read is 0.1x input, cache-write 1.25x input."""
    in_rate, out_rate = _rates(model)
    total = (
        Decimal(int(input_tokens)) * in_rate
        + Decimal(int(output_tokens)) * out_rate
        + Decimal(int(cache_read_tokens)) * in_rate * Decimal("0.1")
        + Decimal(int(cache_creation_tokens)) * in_rate * Decimal("1.25")
    ) / _MILLION
    # 6 dp matches the ledger column; a single Haiku call is ~$0.0015.
    return total.quantize(Decimal("0.000001"))


def usage_from_response(body: Any) -> dict[str, int]:
    """Pull token counts out of an Anthropic /v1/messages response body (the
    ``usage`` object). Tolerant of a missing/oddly-shaped body → all zeros."""
    u = body.get("usage") if isinstance(body, dict) else None
    u = u if isinstance(u, dict) else {}
    return {
        "input_tokens": int(u.get("input_tokens") or 0),
        "output_tokens": int(u.get("output_tokens") or 0),
        "cache_read_tokens": int(u.get("cache_read_input_tokens") or 0),
        "cache_creation_tokens": int(u.get("cache_creation_input_tokens") or 0),
    }


async def record_usage(
    *,
    workspace_id: str,
    kind: str,
    model: str,
    usage: dict[str, int],
    workflow_id: str | None = None,
    lead_id: str | None = None,
) -> Decimal:
    """Price + persist one call: a ledger row + advance the campaign and workspace
    running totals the budget guard reads. Runs under system_scope.

    Fails OPEN: a cost-recording error must NEVER break a send/screen — the work
    already happened and Anthropic already billed it; we log and move on."""
    cost = cost_usd(
        model,
        usage.get("input_tokens", 0),
        usage.get("output_tokens", 0),
        usage.get("cache_read_tokens", 0),
        usage.get("cache_creation_tokens", 0),
    )
    try:
        async with system_scope():
            await execute(
                "INSERT INTO omni_ai_usage (workspace_id, workflow_id, lead_id, kind, model, "
                "input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens, cost_usd) "
                "VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)",
                workspace_id, workflow_id, lead_id, kind, model,
                usage.get("input_tokens", 0), usage.get("output_tokens", 0),
                usage.get("cache_read_tokens", 0), usage.get("cache_creation_tokens", 0),
                cost,
            )
            if workflow_id:
                await execute(
                    "UPDATE omni_workflows SET ai_spend_usd = COALESCE(ai_spend_usd,0) + $2 WHERE id=$1",
                    workflow_id, cost,
                )
            await execute(
                "INSERT INTO omni_ai_workspace_budget (workspace_id, spend_usd) VALUES ($1,$2) "
                "ON CONFLICT (workspace_id) DO UPDATE SET "
                "spend_usd = omni_ai_workspace_budget.spend_usd + $2, updated_at = NOW()",
                workspace_id, cost,
            )
    except Exception:  # noqa: BLE001
        log.exception(
            "record_usage failed (kind=%s model=%s ws=%s) — billed by Anthropic, not recorded",
            kind, model, workspace_id,
        )
    return cost


def _blocks(spend: Any, cap: Any, mode: str | None) -> bool:
    """Does this (spend, cap, mode) block the next paid call? alert never blocks;
    warn_stop and hard_stop both hard-stop once spend has reached the cap."""
    if (mode or DEFAULT_MODE) == MODE_ALERT:
        return False
    return Decimal(str(spend or 0)) >= Decimal(str(cap or 0))


async def budget_blocked(workspace_id: str, workflow_id: str | None) -> tuple[bool, str]:
    """Should the NEXT paid AI call be blocked? Checks the per-campaign cap first,
    then the workspace ceiling. Reads cheap single-row running totals, so it is
    safe on the dispatch hot path.

    Fails OPEN: a check error must NOT block (a broken guard halting a live
    campaign is worse than a missed cap — the ledger is still the source of truth)."""
    try:
        async with system_scope():
            wf = (
                await fetch_one(
                    "SELECT ai_budget_usd, ai_budget_mode, ai_spend_usd FROM omni_workflows WHERE id=$1",
                    workflow_id,
                )
                if workflow_id
                else None
            )
            ws = await fetch_one(
                "SELECT budget_usd, mode, spend_usd FROM omni_ai_workspace_budget WHERE workspace_id=$1",
                workspace_id,
            )
        if wf and wf["ai_budget_usd"] is not None and _blocks(
            wf["ai_spend_usd"], wf["ai_budget_usd"], wf["ai_budget_mode"]
        ):
            return True, "campaign_budget_exceeded"
        if ws and ws["budget_usd"] is not None and _blocks(ws["spend_usd"], ws["budget_usd"], ws["mode"]):
            return True, "workspace_budget_exceeded"
    except Exception:  # noqa: BLE001
        log.exception("budget_blocked check failed — failing open (not blocking)")
    return False, ""
