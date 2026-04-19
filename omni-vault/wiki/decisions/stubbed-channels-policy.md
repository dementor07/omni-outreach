---
title: "ADR: Stubbed Channels Policy"
category: decisions
tags: [channels, SMS, webhook, dispatcher, NodeType, typing]
sources: []
updated: 2026-04-19
---

# ADR: Stubbed Channels Policy

## Status
Accepted — applies to `action_sms`, `action_webhook`, `action_instagram`, `action_telegram`

## Context

Omni supports more outreach channels as UI-selectable options than the backend dispatcher can currently handle. The question is: how should channels that are not yet implemented in the dispatcher be treated in the type system, UI, and runtime?

## Decision

**Wire the full type surface up front; stub only the dispatcher handler.**

Specifically:
1. The channel's `node_type` string is included in the backend `NodeType` Literal (`sequences.py`)
2. The channel's `node_type` is included in the frontend `NodeType` union (`useSequenceSteps.ts`)
3. The channel appears in `NODE_PALETTE` with a real icon and colour
4. The channel appears in the `SequentialBuilder` add-button grid where it makes sense (actions/messaging only — not conditions/events)
5. The channel's `node_type` is in the `nodeTypes` map pointing at `ActionNode`
6. The dispatcher has **no handler** — tasks for this type will be silently skipped or logged as unhandled

## Rationale

### Why wire the full type surface?

- **Type safety**: if the `NodeType` union is incomplete, the TypeScript compiler won't catch invalid node types flowing through the system
- **Database integrity**: if a node type can be added to the canvas but not saved, the user gets a silent data loss bug. Wiring it fully means save/load works correctly
- **Future implementation cost**: adding a dispatcher handler later requires only one function; re-wiring the entire type surface later is 5× the work
- **Demo-ability**: the client can see all planned channels on the UI, even if some are "coming soon"

### Why not block the UI if there's no handler?

We will add visual indicators ("Coming soon" badge or tooltip) in a future pass. For now the silent skip is acceptable because no real leads are queued against unimplemented channels in production — campaigns are configured manually.

### Why not add a dummy handler that logs?

Added to the dispatcher task list; this should be the next step after this ADR is filed. A no-op handler that logs a warning is better than silent dispatch failure.

## Channels and their stub status

| node_type | UI wired | Backend typed | Dispatcher handler |
|-----------|----------|---------------|--------------------|
| `action_sms` | ✅ | ✅ | ❌ (no-op) |
| `action_webhook` | ✅ | ✅ | ❌ (no-op) |
| `action_instagram` | ✅ | ✅ | ❌ (no-op) |
| `action_telegram` | ✅ | ✅ | ❌ (no-op) |

## Pending Work

1. Add a `_handle_sms` and `_handle_webhook` no-op stub to `dispatcher.py` that logs a `WARNING` so stubbed tasks are visible in logs
2. Add a "Coming soon" badge in the palette or builder for these channel types
3. File separate ADRs when each channel is implemented: `sms-implementation.md`, `webhook-crm-integration.md`

## Related Pages
- [[channels]]
- [[canvas-editor]]
- [[dispatcher]]
- [[canvas-ux-decisions]]
