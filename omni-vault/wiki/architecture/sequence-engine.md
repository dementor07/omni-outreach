---
title: Sequence Engine (Event-Driven State Machine)
category: architecture
tags: [sequencer, canvas, graph, nodes, edges, state-machine, events]
sources: [raw/Clippings/Cold Outreach Script Fix.md]
updated: 2026-04-12
---

# Sequence Engine (Event-Driven State Machine)

Omni is an event-driven state machine for outbound systems. It has evolved from a linear sequencer into a system where a Directed Acyclic Graph (DAG) defines the routing blueprint, but execution is entirely reactive: `Event → Decision → Action → State Transition`.

## Core Abstractions

- **Lead**: A stateful object traversing the graph. Its current state is defined by `current_node_id`.
- **Node**: A state transformer.
- **Edge**: A transition rule evaluated when an event occurs.
- **Event**: A trigger for execution (e.g., webhook, timeout) that wakes up a parked lead.

## Node Taxonomy

Nodes share a unified structure (`id, type, subtype, config, position, metadata`) and are categorized as:

1. **Trigger Nodes**: Entry points (e.g., Lead Created, API/Webhook Trigger).
2. **Event Nodes**: Listeners where leads park and wait (e.g., On Reply, On Email Open, On Link Click, On Timeout).
3. **Action Nodes**: Execution steps (e.g., Send Email, Send LinkedIn DM, Start Voice Call via Retell).
4. **Condition Nodes**: Immediate logic gates (e.g., If Replied, If Tag Exists).
5. **Control Nodes**: Flow management (e.g., Delay, Split, End).
6. **Subflow Nodes**: Encapsulate entire sub-graphs recursively (e.g., embedding a Retell conversation flow).

## Graph Traversal & Parking System

Instead of just pushing tasks sequentially, the engine decouples *waiting* from *execution*.

1. **Execution**: When a node completes, the outgoing edges are evaluated, and the next nodes are scheduled via the [[dispatcher]].
2. **Parking**: When a lead hits an Event/Listener node, it pauses. The `leads.current_node_id` is updated, and the dispatcher ignores the lead.
3. **Resumption**: When an external event occurs (e.g., Unipile webhook fires for a reply), the event bus processes it, checks the transition rules for the parked node, applies the state transition, and pushes the new action to the queue.

## DB Tables

- `sequence_nodes` — `id, campaign_id, node_type, data JSONB, position_x, position_y`
- `sequence_edges` — `id, campaign_id, source_node_id, target_node_id, source_handle`
- `queue` — `id, campaign_id, lead_id, node_id, channel, status, scheduled_at`
- `events` — Immutable audit log of all system triggers.

## Related Pages
- [[system-overview]]
- [[dispatcher]]
- [[voice-node]]
- [[canvas-editor]]
