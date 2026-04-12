---
title: Canvas Editor
category: product
tags: [canvas, ReactFlow, xyflow, UX, sequences, telemetry, bandit]
sources: []
updated: 2026-04-12
---

# Canvas Editor

`frontend/src/pages/Campaigns.tsx` — sequence tab when `campaign.sequence_mode === 'canvas'`

## Node Types & Components

| node_type | Component | Notes |
|-----------|-----------|-------|
| `trigger_start` | `TriggerNode` | Dark slate card, no target handle |
| `action_*` | `ActionNode` | Shows Simple/Flow mode badge, configured/draft status |
| `condition_*` | `ConditionNode` | True/False source handles |
| `event_*` | `EventNode` | Single bottom source handle |
| `delay` | `DelayNode` | Inline number input for `delay_days` |
| `split` | `SplitNode` | Shows "Bandit Active" + per-arm win rate % once learned |
| `end` | `EndNode` | Rose terminal card |

## Edge Types

| type | Component | When used |
|------|-----------|-----------|
| `custom` | `CustomEdge` | Default. Bezier with ✕ delete button on select. |
| `telemetry` | `TelemetryEdge` | Active when Live mode on. Heat-colored, floating pill, dashed on backpressure. See [[telemetry-overlay]]. |

## SplitNode — Bandit Display

Reads `node.data.weights` (`{true: {alpha, beta}, false: {alpha, beta}}`).
- No data or default (sum ≤ 4): shows "Learning (50/50)"
- Learned: shows "Bandit Active" + `Math.round(alpha/(alpha+beta)*100)% win rate` per arm

## ConfigSidebar

Right-side panel opens on node click (`selectedNodeId`). Fields:
- All: node type label
- `delay`: `delay_days` input (calls `updateNodeData`)
- `action_email`: account selector + subject + body
- `action_voice`: Standard/Flow toggle + agent + prompt editor / Retell editor link
- Other action nodes: body textarea + template save

## Serialization (Critical)

React callbacks are stripped before DB save:
```ts
const { onChange, onDelete, onEditTemplate, ...serializableData } = n.data as any
```
Prevents non-serializable functions persisting to `sequence_nodes.data JSONB`.

## Save / Load

- Load: `GET /sequences/{campaign_id}` → React Flow nodes + edges
- Save: `POST /sequences/save` — full replace (delete + re-insert all nodes/edges for campaign)

## Live Telemetry Toggle

"Live" button in Panel (top-right). When active:
- Polls `GET /sequences/{id}/telemetry` every 5s
- Edges switch to `type: 'telemetry'`, colored by activity/backpressure
- Radio icon pulses while active

## Related Pages
- [[sequence-engine]]
- [[telemetry-overlay]]
- [[auto-optimization-engine]]
- [[voice-node]]
