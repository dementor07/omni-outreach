---
title: Auto-Optimization Engine (Reinforcement Learning)
category: architecture
tags: [reinforcement-learning, a-b-testing, ml, dag, routing, bandit]
sources: []
updated: 2026-04-12
---

# Auto-Optimization Engine (Multi-Armed Bandit)

`backend/app/services/optimization.py`

Upgrades every `split` node from static 50/50 routing into a **Thompson Sampling Multi-Armed Bandit**. Runs as a background cron every 10 minutes.

## Status: Implemented

## Architecture

### Data Flow

```
leads.path_history (bandit trace)
         ↓
  run_optimization() [cron, every 10min]
         ↓
  _update_node_weights(split_node)
         ↓
  sequence_nodes.data.weights (Beta params updated)
         ↓
  next lead hits split node → Thompson Sample → better arm chosen
```

### Beta Distribution Params

Stored in `sequence_nodes.data.weights`:
```json
{
  "true":  { "alpha": float, "beta": float },
  "false": { "alpha": float, "beta": float }
}
```
Default when no data: `alpha=1, beta=1` (uniform prior → pure 50/50).

### Reward Schedule

| Event type | Reward |
|-----------|--------|
| `invite_accepted` | 1 |
| `email_sent` | 1 |
| `dm_sent` | 1 |
| `reply_received` | 5 |

### Weight Update Formula

For each arm: query all leads whose `path_history` contains `{"split_node_id": X, "arm": "true|false"}`, sum their reward signals from the `events` table.

```
alpha = reward_sum + 1
beta  = max(0, total_leads_on_arm - reward_sum) + 1
```

Minimum `MIN_SAMPLES = 10` per arm required before weights shift — prevents thrashing on small data.

## Sampling at Runtime (sequencer.py)

```python
sample_true  = random.betavariate(weights["true"]["alpha"],  weights["true"]["beta"])
sample_false = random.betavariate(weights["false"]["alpha"], weights["false"]["beta"])
chosen_arm   = "true" if sample_true >= sample_false else "false"
```

Leads are always routed to exactly one arm. Choice is stored in `leads.path_history`.

## Traceability

`leads.path_history JSONB DEFAULT '[]'` — appended on every split traversal:
```json
[
  {"split_node_id": "uuid-of-split-node", "arm": "true"},
  {"split_node_id": "uuid-of-another-split", "arm": "false"}
]
```
Supports multi-split campaigns. Each entry is independently traceable.

## Canvas UI

`SplitNode` in `Campaigns.tsx` reads `node.data.weights` and displays per-arm expected win rates:
- `trueRate = Math.round(alpha / (alpha + beta) * 100)%`
- Shows "Learning (50/50)" until `MIN_SAMPLES` reached, then "Bandit Active" with live %

## Cron Registration

`backend/app/worker/tasks.py`:
```python
cron(optimize_splits, minute=set(range(0, 60, 10)))  # every 10 min
```

## Related Pages
- [[sequence-engine]]
- [[omnichannel-logic-loops]]
- [[autonomous-feedback-loops]]
- [[canvas-editor]]
