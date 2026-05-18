# Agent Runtime Proposal — 2026-05-18

The question: how do we add "agents" — multi-step, tool-using, goal-driven LLM
behaviors — to Omni in a way that's customizable from the canvas without setting
fire to the existing architecture?

Three serious options. Honest assessment of each.

---

## What "agent" means here, concretely

An operator drops an **Agent node** onto the canvas, configures it with:
- a **goal** ("book a discovery call with this lead")
- a **toolset** (subset of: send LinkedIn DM, send email, scrape recent posts,
  check calendar, lookup CRM, mark hot, end sequence, etc.)
- a **budget** (max turns, max tokens, max dollars, max wall-clock time)
- **guardrails** (don't message after 7pm local, don't reference competitors)

On lead arrival, the agent loops: think → pick tool → call tool → observe →
think → … until goal met, budget exhausted, or guardrail fires. Final state
flows out one of: `success` / `gave_up` / `budget_exceeded` / `escalated_to_human`.

This is the same shape as ReAct, AutoGen, or any LangGraph agent. The question is
which substrate.

---

## Option A — LangGraph

**What it is:** Anthropic-friendly, maintained-by-LangChain, agent-specific graph
runtime in Python. Nodes are functions; edges are conditional. Built-in support
for tool calling, checkpoint/resume (Postgres backend), human-in-the-loop,
streaming. Stateful — every step persists. As of late 2025 LangChain has
essentially deprecated the legacy "chain" abstraction in favor of LangGraph.

**Fit with Omni:**
- ✅ Tool-calling is first-class; we'd write `@tool def send_linkedin_dm(...)`
  wrappers around our existing dispatcher handlers.
- ✅ Checkpoint/resume via Postgres works with our existing DB.
- ✅ Async-native (works with FastAPI + asyncpg).
- ⚠️ LangGraph state machines run *inside* the brain (Python process). They
  don't map cleanly onto our canvas's xyflow graph — they'd be invisible to the
  operator-facing graph editor unless we render LangGraph state as a sub-canvas
  inside an Agent node.
- ⚠️ Adds heavy deps: `langgraph`, `langchain-core`, `langchain-anthropic`. The
  combined wheel is sizable.
- ❌ Two graph representations now exist in the codebase — our sequence-graph
  (operator-facing, persisted to `sequence_nodes` + `sequence_edges`) and
  LangGraph's runtime graph (in-process). They have different semantics. This is
  the real cost.

**Operator UX with LangGraph:**
Operator drops an `action_agent` node, picks tools from a checklist, writes the
goal in plain English. Behind the scenes a LangGraph state machine spins up,
runs to budget exhaustion, returns its terminal handle. The operator never
sees the inner graph unless they open an "agent trace" panel.

**Implementation cost:** ~600 LOC backend + dependency install + Postgres
checkpoint table migration + a new `AgentTraceModal` on the frontend. 1–2 days
of focused work. **Real risk:** the LangChain ecosystem is moving fast and
breaks APIs frequently.

---

## Option B — LangChain (legacy chains/agents)

**What it is:** The older `langchain.agents` API. AgentExecutor, ZeroShotReact,
the original LCEL/Runnable model.

**Fit with Omni:**
- ❌ LangChain itself is steering people toward LangGraph for any new agent work.
  Their own docs say "for production agents, use LangGraph." Building on legacy
  LangChain in 2026 is investing in a deprecation path.
- ✅ Lighter dep footprint than LangGraph + LangChain combined, but only
  marginally.
- ❌ No first-class state persistence; you'd build the checkpoint layer yourself.
- ❌ Tool-calling abstractions are clunkier than LangGraph's.

**Verdict:** Don't. This option exists only because you mentioned it in the
question. The LangChain team would tell you not to.

---

## Option C — Hand-rolled on existing primitives

**What it is:** Stay in our codebase. Build an `action_agent` node whose handler
is a tight Python loop that calls Anthropic's tool-use API directly. Tools are
Python functions registered in a new `app/services/agent_tools.py` module —
each tool is just a thin wrapper around existing dispatcher handlers.

**Fit with Omni:**
- ✅ Zero new deps. Uses the `anthropic` SDK we already depend on for AI Compose.
- ✅ Tool-use is a single API parameter (`tools=[...]`) — Anthropic's SDK
  natively handles the loop; we don't need a framework for it.
- ✅ State stays in our existing tables (`agent_runs` table, lives next to
  `lead_gen_runs`). Same query patterns operators already understand.
- ✅ The Agent node is just another `BaseHandler` in the dispatcher — same
  shape as `AIComposeHandler`. No second runtime, no second graph model.
- ⚠️ We re-implement primitives LangGraph already has (retry, checkpoint,
  streaming traces). For now that's fine — operators don't need streaming
  traces yet.
- ⚠️ If agents grow into multi-agent orchestration (one agent calls another),
  we'll re-create LangGraph badly. Worth tracking but not today.

**Operator UX with hand-rolled:**
Same as Option A — operator drops `action_agent`, picks tools, writes goal,
picks budget. They see a Trace tab on the lead drawer that shows turn-by-turn
what the agent did. Built into our existing event log.

**Implementation cost:** ~400 LOC backend (handler + tool registry + 4–6
starter tools) + ~150 LOC frontend (config sidebar + trace viewer). 1 day.

---

## Recommendation

**Option C — hand-rolled.**

Three reasons:

1. **The Anthropic SDK's tool-use API already does ~70% of what LangGraph wraps.**
   You pass `tools=[...]`, the model decides which to call, you execute it,
   return the result, loop until `stop_reason='end_turn'`. That's the whole loop.
   LangGraph adds: checkpoint resume, branching state machines, multi-agent.
   We don't need any of those for v1.

2. **We just spent a session understanding why the canvas has two states
   (xyflow + backend).** Adding a third graph representation (LangGraph's
   in-process state) compounds that. Operators would have to reason about
   "the agent node has its own graph inside, which uses different state."
   Hand-rolled keeps one graph model.

3. **LangChain/LangGraph churn risk.** v0.0.x → v0.1 → v0.2 → v0.3 each broke
   public APIs in 2024-2025. We've seen what happens in this codebase when
   external API contracts drift (the asyncpg jsonb codec bug, the Pydantic
   field-name drift, the sequencer's `condition_has_field` key). I don't want
   another moving contract under us.

**Migration path if Option C outgrows itself:** the hand-rolled `action_agent`
handler can be re-implemented as a LangGraph state-machine inside the same
BaseHandler interface later. No data migration needed. We're not painting
ourselves into a corner.

---

## What "hand-rolled" actually looks like

```python
# app/services/agent_tools.py
from typing import Any
from anthropic import AsyncAnthropic

@tool_registry.register("send_linkedin_dm")
async def send_linkedin_dm(lead_id: str, body: str) -> dict:
    """Send a LinkedIn DM to this lead. Body is the message text."""
    # delegates to existing dispatcher.LinkedInDMHandler
    ...

@tool_registry.register("scrape_recent_post")
async def scrape_recent_post(lead_id: str) -> dict:
    """Returns the lead's most recent LinkedIn post (title + first 200 chars)."""
    ...

@tool_registry.register("mark_hot")
async def mark_hot(lead_id: str, reason: str) -> dict:
    """Tag the lead as hot and notify the operator. Use when intent is clear."""
    ...

@tool_registry.register("end_sequence")
async def end_sequence(lead_id: str, outcome: str) -> dict:
    """Stop pursuing this lead. outcome is one of: success | not_interested | unreachable."""
    ...
```

```python
# app/services/agent.py
class AgentHandler(BaseHandler):
    async def execute(self, task, lead, campaign):
        cfg = node_data
        goal = cfg["goal"]
        toolset = cfg["tools"]            # list of registered tool names
        budget = cfg.get("max_turns", 10)
        max_tokens_total = cfg.get("max_tokens", 10_000)

        tools = [tool_registry.spec(name) for name in toolset]
        messages = [{"role": "user", "content": goal}]
        tokens_used = 0

        for turn in range(budget):
            resp = await client.messages.create(
                model="claude-haiku-4-5-20251001",
                tools=tools,
                messages=messages,
                max_tokens=1024,
            )
            tokens_used += resp.usage.input_tokens + resp.usage.output_tokens
            if tokens_used > max_tokens_total:
                return self._exit("budget_exceeded")

            if resp.stop_reason == "end_turn":
                return self._exit("success")

            if resp.stop_reason == "tool_use":
                tool_results = []
                for block in resp.content:
                    if block.type == "tool_use":
                        result = await tool_registry.run(
                            name=block.name, args=block.input, lead_id=lead["id"]
                        )
                        tool_results.append({
                            "type": "tool_result",
                            "tool_use_id": block.id,
                            "content": json.dumps(result),
                        })
                messages.append({"role": "assistant", "content": resp.content})
                messages.append({"role": "user", "content": tool_results})
                continue

            return self._exit("unexpected_stop")

        return self._exit("gave_up_budget")
```

That's the whole substrate. Every turn is logged to `events` for the trace
viewer. Each terminal state is a different `source_handle` on the Agent node so
the operator can branch in the canvas.

---

## Operator-facing UX (any option)

The Agent node config sidebar:

```
┌─ Agent Node Configuration ───────────────────────────────────┐
│ Goal                                                          │
│ ┌─────────────────────────────────────────────────────────┐ │
│ │ Book a 15-minute discovery call with this lead. Their   │ │
│ │ company is in {{industry}}; tailor the pitch.           │ │
│ └─────────────────────────────────────────────────────────┘ │
│                                                              │
│ Tools                                                        │
│ ☑ send_linkedin_dm     ☑ scrape_recent_post                 │
│ ☑ send_email           ☐ check_calendar                     │
│ ☑ mark_hot             ☑ end_sequence                       │
│ ☐ webhook_callback     ☐ enrich                             │
│                                                              │
│ Budget                                                       │
│ Max turns: [10]   Max tokens: [10000]   Max wall: [5min]    │
│                                                              │
│ Outputs (handles on the canvas)                              │
│ • success         → next node                                │
│ • gave_up         → next node                                │
│ • budget_exceeded → next node                                │
│ • escalated       → next node (when agent calls mark_hot)   │
└──────────────────────────────────────────────────────────────┘
```

Four source handles instead of one. The lead flows out of whichever the agent
landed on.

---

## Decision (2026-05-18)

Shipped Option C with the 5-tool starter set: `send_linkedin_dm`, `send_email`,
`mark_hot`, `add_tag`, `end_sequence`. Code in `backend/app/services/agent.py`
and `backend/app/services/agent_tools.py`. State in `agent_runs` table
(migration 013). Outcome handles match this proposal: success / escalated /
gave_up / budget_exceeded.

See [[architecture-gaps-2026-05-18]] for the broader gap context and
[[node-audit-2026-05-18]] for the per-node truth table.
