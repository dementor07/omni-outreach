---
title: Auto-Optimization Engine (Reinforcement Learning)
category: architecture
tags: [reinforcement-learning, a-b-testing, ml, dag, routing]
sources: []
updated: 2026-04-12
---

# Auto-Optimization Engine (Reinforcement Learning)

Omni's DAG sequencer currently supports static logic gates, notably the `split` control node which routes leads down Path A or Path B at a hardcoded 50/50 ratio. 

To fulfill the vision of an autonomous outbound operating system, we will upgrade the `split` node to function as a **Multi-Armed Bandit** powered by Reinforcement Learning.

## The Concept: Dynamic Edge Weights

Instead of static 50/50 splits, every outgoing edge from an optimization node has a dynamic "Weight" (Probability of Selection). 

### 1. Initialization
A new campaign starts with a `split` node branching to two different paths:
- **Path A (LinkedIn DM)**: Weight 50%
- **Path B (Cold Email)**: Weight 50%

### 2. Reward Signals (The Feedback Loop)
We define "Rewards" based on downstream Event Nodes:
- Lead reaches `event_invite_accepted` = +1 point
- Lead reaches `event_email_opened` = +2 points
- Lead reaches `condition_replied` (True) = +10 points
- Lead reaches `action_voice` (Positive Sentiment) = +50 points

### 3. The Optimization Loop
A background cron job (the Optimization Engine) continuously queries the `events` audit table. It traces backward from a positive Reward Signal up the DAG to see which branch of the `split` node the lead originally took.

Using an algorithm like **Thompson Sampling** or **Upper Confidence Bound (UCB)**, the engine dynamically adjusts the edge weights in `sequence_nodes.data`.

### 4. Autonomous Convergence
Over time (e.g., after 500 leads), the engine might discover that for this specific target audience, Path A (LinkedIn) generates replies at a much higher rate than Path B (Email). 

The engine will automatically adjust the split:
- **Path A**: Weight 85%
- **Path B**: Weight 15% (Kept active for continuous exploration against changing trends).

## Implementation Requirements
1. **Traceability**: `leads` must maintain an array of `path_history` (UUIDs of edges traversed) so rewards can be accurately attributed back to the split nodes.
2. **Algorithm Service**: A new `optimization.py` service running alongside the [[dispatcher]] to recalculate weights periodically.
3. **UI Updates**: The [[canvas-editor]] will display live, pulsing percentage indicators on the edges leaving an optimization node, showing operators how the AI is routing traffic in real-time.

## Related Pages
- [[sequence-engine]]
- [[omnichannel-logic-loops]]
