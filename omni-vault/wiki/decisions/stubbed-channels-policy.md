---
title: "ADR: Stubbed Channels Policy"
category: decisions
tags: [channels, SMS, webhook, dispatcher, NodeType, typing]
sources: []
updated: 2026-04-21
---

# ADR: Stubbed Channels Policy

## Status
Superseded — historical staging ADR from the period before SMS/Webhook/Instagram/Telegram handlers were implemented

## Context

At the time this ADR was written, Omni supported more outreach channels in the UI/type system than the backend dispatcher could actually execute. The question was how to stage those channels safely before real handlers existed.

## Decision

**Historical decision:** wire the full type surface up front, then stub the dispatcher handler until the channel is implemented.

Specifically:
1. The channel's `node_type` string is included in the backend `NodeType` Literal (`sequences.py`)
2. The channel's `node_type` is included in the frontend `NodeType` union (`useSequenceSteps.ts`)
3. The channel appears in `NODE_PALETTE` with a real icon and colour
4. The channel appears in the `SequentialBuilder` add-button grid where it makes sense (actions/messaging only — not conditions/events)
5. The channel's `node_type` is in the `nodeTypes` map pointing at `ActionNode`
6. The dispatcher initially had **no handler** — tasks for this type would be staged for later execution support

## Rationale

### Why wire the full type surface?

- **Type safety**: if the `NodeType` union is incomplete, the TypeScript compiler won't catch invalid node types flowing through the system
- **Database integrity**: if a node type can be added to the canvas but not saved, the user gets a silent data loss bug. Wiring it fully means save/load works correctly
- **Future implementation cost**: adding a dispatcher handler later requires only one function; re-wiring the entire type surface later is 5× the work
- **Demo-ability**: the client can see all planned channels on the UI, even if some are "coming soon"

### Why not block the UI if there's no handler?

At the time, the goal was to avoid data-loss and type-drift while letting the UI expose planned channels.

### Why not add a dummy handler that logs?

That was the next intended step when this ADR was filed. The system has since moved past that stage and now has live handlers.

## Channels and their stub status

| node_type | UI wired | Backend typed | Dispatcher handler |
|-----------|----------|---------------|--------------------|
| `action_sms` | ✅ | ✅ | ✅ live |
| `action_webhook` | ✅ | ✅ | ✅ live |
| `action_instagram` | ✅ | ✅ | ✅ live |
| `action_telegram` | ✅ | ✅ | ✅ live |

## Superseded By

- Live dispatcher handlers for SMS, Webhook, Instagram, and Telegram
- Updated canonical channel/runtime docs in [[channels]], [[dispatcher]], and [[instagram-telegram-integration]]

## Related Pages
- [[channels]]
- [[canvas-editor]]
- [[dispatcher]]
- [[canvas-ux-decisions]]
