# Sequence Engine (SOTA)

## 1. Overview
The Sequence Engine is the "Brain" of Omni. It manages the **DAG (Directed Acyclic Graph)** traversal for every lead.

---

## 2. Orchestration: From Python to Flink
We are moving from a **Procedural Sequencer** to a **Stateful Stream Processor**.

### The Python Sequencer (Legacy/Brain)
- **File**: `app/services/sequencer.py`
- **Role**: High-level graph navigation. 
- **Action**: Publishes `ActionCommand` to the stream and sets the `current_node_id` in Postgres.

### The Flink Journey Orchestrator (Target)
- **Role**: Autonomously manages lead state and timers.
- **Why?**: To handle millions of concurrent "Wait" timers without scanning a database table. Flink's **Keyed Process Function** is the SOTA way to handle this.

---

## 3. Node Types & Transitions
The Engine supports a modular set of nodes:
1. **Trigger**: Intake from Scrapers or Webhooks.
2. **Action**: `email`, `linkedin_dm`, `voice_call`.
3. **Delay**: A "Wait" period managed by **Flink Timers**.
4. **Condition**: Branching logic based on "Replied", "Clicked", or AI Sentiment.

---

## 4. The Event Loop
1. **Execution Result** arrives in the `outreach.results` topic.
2. **Sequencer** (or Flink) consumes the result.
3. **Graph Walker** finds the next edge based on the result handle.
4. **Action Command** is published for the next node.
5. **UI Update**: A `StateTransition` event is emitted to update the Lead's position on the user's screen instantly.

---

## 5. Persistence
- **Graph Metadata**: Still stored in Postgres (`sequence_nodes`, `sequence_edges`).
- **In-Flight State**: Stored in **Flink Checkpoints** (for durability) and **DragonflyDB** (for UI speed).


---

## 6. 2026-05-17 Status

- **Python sequencer is still the only thing advancing leads in production.** `app/services/sequencer.py` walks the DAG, publishes `ActionCommand` to `outreach.commands`, and updates `queue` + `leads` directly.
- **Flink is not deployed yet.** `transition-worker` is up as a consumer but has no producer on the other end. Section 2's "Target" remains target.
- **Bridge path**: when Flink eventually emits to `outreach.transitions`, `transition_worker.py` calls `queue_next_nodes(lead_id, source_node_id, handle)` to re-enter this engine. Field-name mismatch with the Pydantic `StateTransition` model is the active gap — see [[sota-event-schemas]] §6.
- **2026-05-15 lesson**: a SQL `executed_at` column reference (column never existed in `queue`) bricked Queue + Sequence tabs for 8 days before the chrome-devtools-mcp loop caught it on a single page load. See [[postmortem-queue-sequence-crash-may-2026]] and [[chrome-devtools-mcp-loop]]. Outcome: ESLint `react-hooks/rules-of-hooks` gate + global ErrorBoundary now mandatory.
- **Queue schema reality** (for graph-walker writes): `queue` has `scheduled_at`, `locked_at`, `sent_at` — **no `executed_at`**. Both `step_id` (legacy) and `node_id` (current) FKs exist. See [[database]].
