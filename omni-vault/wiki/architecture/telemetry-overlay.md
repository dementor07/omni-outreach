---
title: Canvas Telemetry Overlay
category: architecture
tags: [canvas, ui, ux, event-bus, telemetry, observability]
sources: [infranodus/ontology.md]
updated: 2026-04-12
---

# Canvas Telemetry Overlay

## Context (Knowledge Graph Insight)
Network analysis of the `omni-vault` ontology exposed **Gap B**: The `[Event Bus]` (Redis/Kafka handling thousands of webhooks per second) is completely disconnected from the `[Canvas Editor]` UI. The massive throughput and backpressure of the outreach engine are invisible to the human operator, defeating the purpose of a "Control Plane."

## The Insight: Data as Flow
Instead of hiding the event throughput in a separate "Analytics" dashboard or `queue.py` list, we must pipe the live Redis Stream metrics directly onto the edges of the ReactFlow graph.

## Architectural Implementation

### 1. Live Edge Weights (The "Glowing" Paths)
The `CustomEdge` component in `@xyflow/react` will subscribe to a Server-Sent Events (SSE) or WebSocket endpoint driven by the Event Bus.
- As webhooks fire (e.g., `event_email_opened`), the edge connecting `action_email` to the next node will physically pulse or thicken.
- The color temperature of the edge will shift from cool (slate) to hot (sky/emerald) based on the velocity of leads traversing it in the last 60 seconds.

### 2. Node Backpressure Indicators
If the Dispatcher queue for `action_linkedin_dm` hits the daily cap, the node will render a "Pressure" halo (e.g., amber warning outline), instantly alerting the operator that a bottleneck has formed in the DAG.

### 3. The ReactFlow `EdgeLabelRenderer` Update
We will update the `edgeTypes` to include a `TelemetryEdge` which floats a live counter of leads currently parked or traversing that specific path, completely eliminating the need for a separate analytics screen.

## Related Pages
- [[knowledge-graphs]]
- [[event-bus-architecture]]
- [[canvas-editor]]
