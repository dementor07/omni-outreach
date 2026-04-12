---
title: Canvas Telemetry Overlay
category: architecture
tags: [canvas, ui, ux, event-bus, telemetry, observability]
sources: [infranodus/ontology.md]
updated: 2026-04-12
---

# Canvas Telemetry Overlay

## Status: Implemented

## Backend

`GET /sequences/{campaign_id}/telemetry` in `backend/app/routers/sequences.py`

Returns:
```json
{
  "activity":    { "<node_id>": <count_sent_in_last_60s> },
  "backpressure": { "<node_id>": <count_queued_or_locked> }
}
```

Queries `queue` table grouped by `node_id` (source node). No joins needed — `node_id` IS the source node of the completed/pending task.

## Frontend

`frontend/src/pages/Campaigns.tsx`

### TelemetryEdge component

Replaces `CustomEdge` when Live mode is on. Reads `data.activity` and `data.backpressure` (merged into edge state by the polling effect).

| Activity | Stroke color |
|----------|-------------|
| 0 | slate (`#e2e8f0`) |
| 1–3 | sky-300 (`#7dd3fc`) |
| 4–9 | sky-400 (`#38bdf8`) |
| 10+ | emerald-500 (`#10b981`) |
| backpressure > 5 | amber (`#f59e0b`) + dashed stroke |

Stroke width scales: `2 + min(activity × 0.4, 3)`. Transition: `stroke 0.8s`.

Shows a floating green pill with lead count if `activity > 0`. Shows amber `⏳N` pill if `backpressure > 5`.

### Live Toggle

"Live" button (with pulsing `<Radio />` icon) in the canvas Panel (top-right). Toggles `liveMode` boolean.

### Polling Effect

When `liveMode && activeTab === 'sequence' && id`:
- Polls `GET /sequences/{id}/telemetry` immediately + every 5s
- On update: `setEdges(eds => eds.map(e => ({ ...e, type: 'telemetry', data: { ...e.data, activity: ..., backpressure: ... } })))`

When `liveMode` off: edges reset to `type: 'custom'`.

## Related Pages
- [[event-bus-architecture]]
- [[canvas-editor]]
- [[dispatcher]]
