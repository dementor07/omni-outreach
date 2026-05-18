"""Hand-rolled action_agent runtime (Option C from AGENT_RUNTIME.md).

A tight loop over Anthropic's tool-use API. Tools are registered in
``agent_tools.registry``. Each turn:

    1. Call Claude with the goal + current message history + tool specs.
    2. If stop_reason == 'end_turn' → outcome = success.
    3. If stop_reason == 'tool_use' → run each tool, feed results back, loop.
    4. If turn or token budget exceeded → outcome = budget_exceeded / gave_up.
    5. Persist trace + outcome to agent_runs.

Terminal outcomes map to source_handles on the action_agent node so the canvas
can branch downstream: success | gave_up | budget_exceeded | escalated.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from app.db import execute, fetch_one
from app.services.agent_tools import registry as tool_registry
from app.services.agent_tools import serialize_trace_entry, trace_dump

log = logging.getLogger(__name__)


DEFAULT_AGENT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_MAX_TURNS = 10
DEFAULT_MAX_TOKENS = 10_000


async def run_agent(
    *,
    lead_id: str,
    campaign_id: str,
    node_id: str | None,
    goal: str,
    toolset: list[str],
    max_turns: int = DEFAULT_MAX_TURNS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    default_email_account_id: str | None = None,
    model: str = DEFAULT_AGENT_MODEL,
) -> tuple[str, str]:
    """Run the agent loop. Returns (run_id, outcome_handle).

    outcome_handle is one of: 'success' | 'gave_up' | 'budget_exceeded' | 'escalated'.
    """
    from app.config import settings
    import anthropic

    run_id = str(uuid.uuid4())
    started_at = datetime.now(UTC)

    await execute(
        """
        INSERT INTO agent_runs (id, lead_id, campaign_id, node_id, goal, toolset, max_turns, max_tokens, status, started_at)
        VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, 'running', $9)
        """,
        run_id,
        lead_id,
        campaign_id,
        node_id,
        goal,
        json.dumps(toolset),
        max_turns,
        max_tokens,
        started_at,
    )

    if not getattr(settings, "anthropic_api_key", None):
        await _finalize(run_id, "gave_up", "no anthropic_api_key configured", trace=[])
        return run_id, "gave_up"

    client = anthropic.AsyncAnthropic(api_key=settings.anthropic_api_key)
    tools = tool_registry.filtered_specs(toolset)
    if not tools:
        await _finalize(run_id, "gave_up", "no tools enabled for agent", trace=[])
        return run_id, "gave_up"

    ctx: dict[str, Any] = {
        "lead_id": lead_id,
        "campaign_id": campaign_id,
        "default_email_account_id": default_email_account_id,
    }

    messages: list[dict] = [{"role": "user", "content": goal}]
    trace: list[dict] = [serialize_trace_entry(0, "goal", goal)]
    tokens_used = 0
    outcome: str | None = None
    turn = 0

    for turn in range(1, max_turns + 1):
        try:
            resp = await client.messages.create(
                model=model,
                max_tokens=1024,
                tools=tools,
                messages=messages,
            )
        except Exception as e:  # noqa: BLE001
            log.exception(f"[agent {run_id}] LLM call failed at turn {turn}: {e}")
            trace.append(serialize_trace_entry(turn, "error", str(e)[:300]))
            outcome = "gave_up"
            break

        tokens_used += (resp.usage.input_tokens or 0) + (resp.usage.output_tokens or 0)
        if tokens_used > max_tokens:
            trace.append(serialize_trace_entry(turn, "budget", {"tokens_used": tokens_used, "limit": max_tokens}))
            outcome = "budget_exceeded"
            break

        # Capture model text + any tool calls for the trace.
        text_blocks = [b.text for b in resp.content if getattr(b, "type", None) == "text"]
        if text_blocks:
            trace.append(serialize_trace_entry(turn, "assistant_text", "\n".join(text_blocks)[:1000]))

        if resp.stop_reason == "end_turn":
            outcome = "success"
            break

        if resp.stop_reason == "tool_use":
            tool_uses = [b for b in resp.content if getattr(b, "type", None) == "tool_use"]
            tool_results: list[dict] = []
            for tu in tool_uses:
                trace.append(serialize_trace_entry(
                    turn, "tool_use", {"name": tu.name, "input": tu.input}
                ))
                result = await tool_registry.run(tu.name, tu.input, ctx)
                trace.append(serialize_trace_entry(
                    turn, "tool_result", {"name": tu.name, "result": result}
                ))
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": tu.id,
                    "content": json.dumps(result, ensure_ascii=False),
                })

            messages.append({"role": "assistant", "content": resp.content})
            messages.append({"role": "user", "content": tool_results})

            if ctx.get("_terminal"):
                outcome = "escalated" if any(
                    isinstance(r, dict) and r.get("escalated") for r in (te.get("payload", {}).get("result") for te in trace if te.get("kind") == "tool_result")
                ) else "success"
                break
            continue

        trace.append(serialize_trace_entry(turn, "unexpected_stop", str(resp.stop_reason)))
        outcome = "gave_up"
        break

    if outcome is None:
        outcome = "budget_exceeded"

    # Override to 'escalated' if any tool result flagged it (e.g. mark_hot).
    escalated = any(
        isinstance(te.get("payload"), dict)
        and isinstance(te["payload"].get("result"), dict)
        and te["payload"]["result"].get("escalated")
        for te in trace
        if te.get("kind") == "tool_result"
    )
    if escalated and outcome == "success":
        outcome = "escalated"

    await _finalize(run_id, outcome, None, trace=trace, turns_used=turn, tokens_used=tokens_used)
    return run_id, outcome


async def _finalize(
    run_id: str,
    outcome: str,
    note: str | None,
    *,
    trace: list[dict],
    turns_used: int = 0,
    tokens_used: int = 0,
) -> None:
    await execute(
        """
        UPDATE agent_runs
        SET status='completed', outcome=$2, trace=$3::jsonb,
            turns_used=$4, tokens_used=$5, finished_at=NOW()
        WHERE id=$1
        """,
        run_id,
        outcome,
        trace_dump(trace + ([] if not note else [{"turn": -1, "kind": "note", "payload": note}])),
        turns_used,
        tokens_used,
    )
