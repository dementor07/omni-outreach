---
title: Sequential Builder
category: product
tags: [builder, UI, sequences, linear, delay]
sources: []
updated: 2026-04-12
---

# Sequential Builder

When a campaign is set to `sequence_mode: 'sequential'`, the UI renders the `SequentialBuilder.tsx` component instead of the ReactFlow nodal canvas.

## Dual-Mode Compatibility

The Sequential Builder provides a simpler, top-down linear list interface for creating outreach flows. However, under the hood, it shares the exact same Database architecture and Directed Acyclic Graph (DAG) state structure as the [[canvas-editor]].

- **Compilation**: Adding, moving, or removing steps in the linear list dynamically computes and re-wires the underlying `nodes` and `edges` arrays.
- **Save Payload**: Saving the sequential list posts the identical JSON structure (nodes and directed edges) to `POST /sequences/save` as the canvas does.

## Key Features

- **Interactive Wait Durations**: `delay` steps feature an inline numeric input allowing users to directly edit the wait duration (`delay_days`). Modifying this input updates the underlying node's `data` payload instantly, keeping the UI state perfectly in sync with the graph state.
- **Reordering**: Built-in up/down arrows allow users to reorder steps, which automatically deletes and recreates the intervening edges linearly.
- **Template Configuration**: Action nodes feature a "Script" button, opening the identical `TemplateModal` used in the canvas to edit email subjects, message bodies, and voice agent assignments.

## Related Pages
- [[campaigns]]
- [[canvas-editor]]
- [[sequence-engine]]
