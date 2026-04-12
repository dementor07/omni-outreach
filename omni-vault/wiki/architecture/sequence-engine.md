---
title: Sequence Engine
category: architecture
tags: [sequencer, canvas, graph, nodes, edges, queue]
sources: []
updated: 2026-04-12
---

# Sequence Engine

The sequence engine drives outreach by walking a directed graph of nodes and queueing action tasks for each lead.

## Node Types

| Node Type | Description |
|-----------|-------------|
| `trigger_start` | Entry point — always present, no config |
| `action_linkedin_invite` | Send LinkedIn connection request |
| `action_linkedin_dm` | Send LinkedIn direct message |
| `action_whatsapp` | Send WhatsApp message via Unipile |
| `action_email` | Send email via SMTP |
| `action_voice` | Make AI voice call via Retell |
| `action_instagram` | Instagram DM (stub — not implemented) |
| `action_telegram` | Telegram DM (stub — not implemented) |
| `delay` | Wait N days before continuing |
| `condition_replied` | Branch: has lead replied? True/False edges |

## DB Tables

- `sequence_nodes` — `id, campaign_id, node_type, data JSONB, position_x, position_y`
- `sequence_edges` — `id, campaign_id, source_node_id, source_handle, target_node_id`
- `queue` — `id, campaign_id, lead_id, node_id, channel, status, scheduled_at`

## Graph Traversal (`sequencer.py`)

```
schedule_sequence(lead_id)
  → finds trigger_start node
  → calls queue_next_nodes(lead_id, trigger_start_id)

queue_next_nodes(lead_id, source_node_id, handle, accumulated_delay)
  → for each edge from source:
      action_*  → INSERT into queue with scheduled_at = now + accumulated_delay
      delay     → accumulated_delay += delay_days, recurse
      condition_replied → if replied: follow "true" edge
                          else: park lead (UPDATE leads SET current_node_id)
```

Key design: `accumulated_delay` is passed recursively so delay nodes compound correctly — actions downstream of multiple delays schedule at the sum of all delays.

## Parking & Re-evaluation

When a lead hits `condition_replied` without having replied, it parks:
- `leads.current_node_id` = the condition node id
- When a reply webhook fires → `evaluate_conditions(lead_id)` checks `replied_at` and advances the true branch

## Canvas Modes

Campaigns have `sequence_mode: 'canvas' | 'sequential'`.
- **Canvas** — drag-drop @xyflow/react editor in `Campaigns.tsx`
- **Sequential** — linear list editor via `SequentialBuilder.tsx`

## Related Pages
- [[system-overview]]
- [[dispatcher]]
- [[voice-node]]
- [[canvas-editor]]
