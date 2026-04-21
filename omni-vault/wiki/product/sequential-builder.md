---
title: Sequential Builder
category: product
tags: [builder, UI, sequences, linear, delay]
sources: []
updated: 2026-04-21
---

# Sequential Builder

When a campaign uses `sequence_mode: 'sequential'`, the UI renders `SequentialBuilder.tsx` instead of the full ReactFlow canvas.

## Dual-Mode Compatibility

The builder is a simpler top-down list view over the same underlying graph model used by the [[canvas-editor]].

- **Compilation**: adding, moving, or removing steps recalculates the underlying `nodes` and `edges` arrays.
- **Save payload**: saving posts the same `POST /sequences/save` graph payload as the canvas.
- **Shared templates**: action nodes still use the same template/config sidebar as canvas mode.

## Curated Add-Step Grid

The bottom 2-column (lg: 4-column) add grid now exposes a curated 16-button subset of the most common linear actions and conditions.

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
| Enrich Lead | `action_enrich` | indigo-500 |
| Wait | `delay` | amber-500 |
| AI Screen | `condition_ai_screen` | violet-500 |
| Source Router | `condition_lead_source` | cyan-500 |
| If Has Field | `condition_has_field` | amber-500 |
| End | `end` | rose-500 |

This is intentionally not every backend-supported node. The builder favors common linear flows, while the [[canvas-editor]] exposes the full graph surface.

## STEP_LABELS Map

Human-readable display names live in the `STEP_LABELS` constant. This prevents raw `node_type` strings from leaking into the list UI.

## StepIcon Component

`StepIcon` can render more than the curated add grid exposes. It includes icons for additional node types such as Instagram, Telegram, profile view, events, split nodes, and lead-source routing so pre-existing graphs still render cleanly even if those steps were not added from the linear UI.

## Key Features

- **Interactive Wait Durations**: `delay` steps expose an inline numeric editor for `delay_days`.
- **Reordering**: up/down arrows rebuild the linear edge chain automatically.
- **Template Configuration**: action nodes expose an `Edit Template` button that opens the shared config/template surface.
- **Save Sequence**: sky-500 button in the header calls `onSave(nodes, edges)`.

## Related Pages

- [[campaigns]]
- [[canvas-editor]]
- [[sequence-engine]]
