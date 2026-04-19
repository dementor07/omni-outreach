---
title: Sequential Builder
category: product
tags: [builder, UI, sequences, linear, delay]
sources: []
updated: 2026-04-19
---

# Sequential Builder

When a campaign is set to `sequence_mode: 'sequential'`, the UI renders the `SequentialBuilder.tsx` component instead of the ReactFlow nodal canvas.

## Dual-Mode Compatibility

The Sequential Builder provides a simpler, top-down linear list interface for creating outreach flows. Under the hood it shares the exact same database architecture and Directed Acyclic Graph (DAG) state structure as the [[canvas-editor]].

- **Compilation**: Adding, moving, or removing steps in the linear list dynamically computes and re-wires the underlying `nodes` and `edges` arrays.
- **Save Payload**: Saving the sequential list posts the identical JSON structure to `POST /sequences/save` as the canvas does.

## Add-Step Grid

A 2-column (lg: 4-column) grid at the bottom of the builder surfaces 12 add buttons (expanded Apr 2026 from 4):

| Button label | node_type | Icon colour |
|---|---|---|
| Send Invite | `action_linkedin_invite` | sky-600 |
| LinkedIn DM | `action_linkedin_dm` | sky-500 |
| InMail | `action_linkedin_inmail` | indigo-500 |
| Email | `action_email` | slate-500 |
| WhatsApp | `action_whatsapp` | emerald-500 |
| SMS | `action_sms` | teal-500 |
| AI Voice | `action_voice` | indigo-500 |
| Webhook | `action_webhook` | orange-500 |
| Add Tag | `action_add_tag` | slate-500 |
| Remove Tag | `action_remove_tag` | slate-400 |
| Wait | `delay` | amber-500 |
| End | `end` | rose-500 |

> `action_sms` and `action_webhook` are wired through the UI and backend `NodeType` but the dispatcher has no handler yet — they will silently no-op until implemented.

## STEP_LABELS Map

Human-readable display names for each node type are maintained in the `STEP_LABELS` constant in `SequentialBuilder.tsx`. This prevents raw `node_type` strings from surfacing in the UI.

## StepIcon Component

Each step card renders a `StepIcon` switch for a semantically correct icon per type (Linkedin, Mail, MessageSquare, MessageCircle, Phone, Webhook, Tag, MinusCircle, GitBranch, Bell, Clock, Shuffle, StopCircle). Unknown types fall back to `<Zap>`.

## Key Features

- **Interactive Wait Durations**: `delay` steps feature an inline numeric input allowing users to directly edit the wait duration (`delay_days`). Modifying this input updates the underlying node's `data` payload instantly.
- **Reordering**: Built-in up/down arrows allow users to reorder steps, which automatically deletes and recreates the intervening edges linearly.
- **Template Configuration**: Action nodes feature an "Edit Template" button, opening the `ConfigSidebar` (same sidebar used in canvas mode) to edit message bodies, email subjects, and voice agent assignments.
- **Save Sequence button**: Sky-500 button in the header, calls `onSave(nodes, edges)` → `POST /sequences/save`.

## Related Pages
- [[campaigns]]
- [[canvas-editor]]
- [[sequence-engine]]
