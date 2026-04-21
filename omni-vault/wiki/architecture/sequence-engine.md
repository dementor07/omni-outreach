---
title: Sequence Engine (Event-Driven State Machine)
category: architecture
tags: [sequencer, canvas, graph, nodes, edges, state-machine, events, bandit, lead-gen]
sources: [raw/Clippings/Cold Outreach Script Fix.md]
updated: 2026-04-21
---

# Sequence Engine (Event-Driven State Machine)

`backend/app/services/sequencer.py`

Omni is an event-driven state machine for outbound systems. Execution is reactive: `Event → Decision → Action → State Transition`.

## Core Abstractions

- **Lead**: stateful object tracked by `leads.current_node_id`, `source`, and `path_history`
- **Node**: state transformer in the campaign graph
- **Edge**: transition rule keyed by output handle
- **Event**: signal that resumes parked leads or enriches campaign telemetry

## Canonical Node Contract

The backend `NodeType` in `backend/app/routers/sequences.py` is the persistence contract. It currently supports 27 node types:

| Type | Category | Behavior |
|------|----------|----------|
| `trigger_start` | Trigger | DAG entry point |
| `action_linkedin_invite` | Action | Queues LinkedIn invite task |
| `action_linkedin_dm` | Action | Queues LinkedIn DM task |
| `action_linkedin_inmail` | Action | Queues InMail task |
| `action_linkedin_profile_view` | Action | Queues profile view task |
| `action_email` | Action | Queues email task |
| `action_whatsapp` | Action | Queues WhatsApp task |
| `action_sms` | Action | Queues Twilio SMS task |
| `action_instagram` | Action | Queues Instagram DM task |
| `action_telegram` | Action | Queues Telegram DM task |
| `action_voice` | Action | Queues voice call task |
| `action_webhook` | Action | Queues outbound webhook task |
| `action_add_tag` | Action | Queues tag append task |
| `action_remove_tag` | Action | Queues tag remove task |
| `action_enrich` | Action | Queues provider-based enrichment task |
| `condition_replied` | Condition | Parks if `lead.replied_at IS NULL`; advances True branch if replied |
| `condition_linkedin_distance` | Condition | Immediate — True if `lead.linkedin_distance == 'FIRST_DEGREE'` |
| `condition_tag_exists` | Condition | Immediate — True if tag exists in `lead.tags[]` |
| `condition_ai_screen` | Condition | Immediate — `screener.screen_lead()` verdict routes to `true` / `false` |
| `condition_lead_source` | Condition | Immediate — routes by `lead.source` or `default` |
| `condition_has_field` | Condition | Immediate — checks one lead field for presence |
| `event_invite_accepted` | Event / Listener | Parks until `lead.accepted_at` is set |
| `event_email_opened` | Event / Listener | Parks until `lead.email_opened_at` is set |
| `event_link_clicked` | Event / Listener | Parks until `lead.link_clicked_at` is set |
| `delay` | Control | Accumulates `timedelta(days=delay_days)` without parking |
| `split` | Control | Thompson Sampling over `node.data.weights` |
| `end` | Control | Terminates execution |

## Important Boundary Note

The frontend TypeScript union still contains dormant `wait_until` and `goal` members, but those are not accepted by the backend `NodeType` contract and are not part of the shipped persisted engine.

## DB Tables

- `sequence_nodes` — `id UUID, campaign_id, node_type, data JSONB, position_x, position_y`
- `sequence_edges` — `id UUID, campaign_id, source_node_id, target_node_id, source_handle`
- `queue` — `id, campaign_id, lead_id, node_id, channel, status, scheduled_at, sent_at`
- `events` — immutable audit log: `lead_id, campaign_id, event_type, channel, meta, occurred_at`
- `leads` — `current_node_id UUID`, `source`, `path_history JSONB DEFAULT '[]'`

## Functions

### `schedule_new_lead(lead_id)`

Entry point for freshly scraped leads. Finds the campaign's `trigger_start` node and calls `queue_next_nodes(lead_id, start_node_id)`.

This is what connects [[lead-sources-ui]] into the sequence engine: new leads from provider runs do not need `accepted_at` and can enter immediately.

### `schedule_sequence(lead_id)`

Resume path for accepted LinkedIn leads. Requires `lead.accepted_at IS NOT NULL`. Called by `dispatcher._check_acceptances()`.

### `queue_next_nodes(lead_id, source_node_id, handle='default', accumulated_delay=timedelta(0))`

Core traversal loop. For each outgoing edge from `source_node_id` matching `handle`:

- **action_*** → inserts a queue row with `scheduled_at = NOW() + accumulated_delay`
- **delay** → adds `timedelta(days=delay_days)` and recurses
- **condition_replied** → parks or advances True
- **condition_linkedin_distance** → immediate True/False branch
- **condition_ai_screen** → calls `screen_lead(headline, screening_prompt)` and routes on ACCEPT vs REJECT
- **condition_lead_source** → routes by `lead.source` to a configured handle or `default`
- **condition_has_field** → checks one configured field (`email`, `linkedin_url`, `company`, etc.)
- **split** → samples Beta distributions, records the chosen arm in `leads.path_history`, then recurses
- **event_*** → parks until the relevant signal is present, otherwise advances True immediately if already satisfied
- **end** → terminal no-op

### `evaluate_conditions(lead_id)`

Called when lead state changes (reply received, invite accepted, event fired). If the parked node is now satisfied, the sequencer advances the True branch and clears `current_node_id`.

## Split Node — Thompson Sampling

`node.data.weights` structure:

```json
{
  "true": { "alpha": 12.0, "beta": 4.0 },
  "false": { "alpha": 3.0, "beta": 8.0 }
}
```

- Default: `alpha=1`, `beta=1` for both arms
- Runtime: `random.betavariate(alpha, beta)` sampled per arm
- Trace storage: `leads.path_history` appends `[{"split_node_id": "uuid", "arm": "true"}]`

## Graph Traversal & Parking System

1. **Execution**: node completes, outgoing edges are evaluated, next nodes are queued.
2. **Parking**: event/listener nodes and reply conditions can store `leads.current_node_id`.
3. **Resumption**: webhooks or background checks call `evaluate_conditions()` and resume the graph.

## Related Pages

- [[dispatcher]]
- [[lead-gen-canvas-integration]]
- [[lead-sources-ui]]
- [[auto-optimization-engine]]
- [[canvas-editor]]
- [[event-bus-architecture]]
