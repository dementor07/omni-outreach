---
title: Sequence Engine (Event-Driven State Machine)
category: architecture
tags: [sequencer, canvas, graph, nodes, edges, state-machine, events, bandit]
sources: [raw/Clippings/Cold Outreach Script Fix.md]
updated: 2026-04-12
---

# Sequence Engine (Event-Driven State Machine)

`backend/app/services/sequencer.py`

Omni is an event-driven state machine for outbound systems. Execution is entirely reactive: `Event → Decision → Action → State Transition`.

## Core Abstractions

- **Lead**: stateful object, position tracked by `leads.current_node_id`
- **Node**: state transformer — see taxonomy below
- **Edge**: transition rule, evaluated when event fires
- **Event**: external signal (webhook, timeout) that resumes a parked lead

## Node Taxonomy

| Type | Category | Behavior |
|------|----------|----------|
| `trigger_start` | Trigger | DAG entry point |
| `action_linkedin_invite` | Action | Queues invite task |
| `action_linkedin_dm` | Action | Queues DM task |
| `action_linkedin_inmail` | Action | Queues InMail task |
| `action_linkedin_profile_view` | Action | Queues profile view task |
| `action_email` | Action | Queues email task |
| `action_whatsapp` | Action | Queues WhatsApp task |
| `action_instagram` | Action | Queues Instagram DM task |
| `action_telegram` | Action | Queues Telegram DM task |
| `action_voice` | Action | Queues voice call task |
| `action_add_tag` | Action | Queues tag append task |
| `action_remove_tag` | Action | Queues tag remove task |
| `delay` | Control | Accumulates `timedelta(days=delay_days)` — does NOT park, just offsets scheduled_at |
| `split` | Control | Multi-Armed Bandit — Thompson Samples from `node.data.weights` to pick arm |
| `end` | Control | Terminates sequence |
| `condition_replied` | Condition | Parks if `lead.replied_at IS NULL`; advances True branch if replied |
| `condition_linkedin_distance` | Condition | Immediate — True if `lead.linkedin_distance == 'FIRST_DEGREE'` |
| `condition_tag_exists` | Condition | Immediate — True if tag in `lead.tags[]` |
| `event_invite_accepted` | Event/Listener | Parks until `lead.accepted_at` set |
| `event_email_opened` | Event/Listener | Parks until `lead.email_opened_at` set |
| `event_link_clicked` | Event/Listener | Parks until `lead.link_clicked_at` set |

## DB Tables

- `sequence_nodes` — `id UUID, campaign_id, node_type, data JSONB, position_x, position_y`
- `sequence_edges` — `id UUID, campaign_id, source_node_id, target_node_id, source_handle`
- `queue` — `id, campaign_id, lead_id, node_id, channel, status, scheduled_at, sent_at`
- `events` — immutable audit log: `lead_id, campaign_id, event_type, channel, meta, occurred_at`
- `leads` — `current_node_id UUID` (parking position), `path_history JSONB DEFAULT '[]'` (bandit trace)

## Functions

### `schedule_new_lead(lead_id)`
Entry point for freshly scraped leads (no `accepted_at` required). Finds `trigger_start` node for the campaign → calls `queue_next_nodes(lead_id, start_node_id)`.

### `schedule_sequence(lead_id)`
Entry point called after invite acceptance. Requires `lead.accepted_at IS NOT NULL`. Same flow as above. Called by `dispatcher._check_acceptances()`.

### `queue_next_nodes(lead_id, source_node_id, handle='default', accumulated_delay=timedelta(0))`
Core traversal function. For each outgoing edge from `source_node_id` matching `handle`:
- **action_*** → inserts into `queue` with `scheduled_at = NOW() + accumulated_delay`
- **delay** → accumulates `timedelta(days=delay_days)`, recurses with new delay
- **condition_replied** → parks (sets `current_node_id`) if not replied; advances True branch if replied
- **condition_linkedin_distance** → immediate True/False branch based on `lead.linkedin_distance`
- **split** → Thompson Sampling: samples `Beta(α, β)` for each arm, picks winner, records in `leads.path_history`, recurses into chosen arm
- **event_*** → parks if event not yet occurred; advances True branch if already occurred
- **end** → no-op (terminal)

### `evaluate_conditions(lead_id)`
Called when lead state changes (reply received, event fired). Checks if `lead.current_node_id` is a parkable node whose condition is now satisfied. If so: advances True branch, clears `current_node_id`.

## Split Node — Thompson Sampling

`node.data.weights` structure:
```json
{
  "true":  { "alpha": 12.0, "beta": 4.0 },
  "false": { "alpha": 3.0,  "beta": 8.0 }
}
```
- Default (no data): `alpha=1, beta=1` for both arms → pure 50/50 exploration
- `random.betavariate(alpha, beta)` sampled for each arm → higher sample wins
- Choice recorded in `leads.path_history`:
  ```json
  [{"split_node_id": "uuid", "arm": "true"}]
  ```

## Graph Traversal & Parking System

1. **Execution**: node completes → outgoing edges evaluated → next nodes queued
2. **Parking**: lead hits Event/Listener node → `leads.current_node_id` set → dispatcher ignores lead
3. **Resumption**: external event fires → `evaluate_conditions()` called → condition satisfied → advance True branch, clear `current_node_id`

## Related Pages
- [[dispatcher]]
- [[auto-optimization-engine]]
- [[canvas-editor]]
- [[event-bus-architecture]]
