---
title: ADR — Voice Node Architecture
category: decisions
tags: [ADR, voice, retell, nested-flow, canvas]
sources: []
updated: 2026-04-12
---

# ADR: Voice Node — Standard vs Nested Flow

**Date:** 2026-04-12
**Status:** Active

## Context

The voice node needed to support two fundamentally different AI call styles:
1. A single freeform prompt where the AI improvises (good for demo calls, relationship building)
2. A deterministic nodal conversation flow with explicit branching (good for structured qualification, specific objection handling paths)

Retell AI natively supports both as separate agent types (`retell-llm` and `conversation-flow`).

## Decision

Map Retell's two agent types directly to a **Standard / Nested Flow toggle** on the voice node in Omni's canvas.

- **Standard** → `retell-llm` — expose `begin_message` + `general_prompt` directly in ConfigSidebar
- **Nested Flow** → `conversation-flow` — open a full ReactFlow sub-canvas (`RetellFlowEditor`) that reads/writes the Retell conversation flow graph directly

The sub-canvas embeds one nodal graph system (Retell's conversation flow) inside another (Omni's sequence canvas). This is intentional — "nodal graphs within nodal graphs" is a core product vision.

## Consequences

- Omni becomes the editor for Retell flows — users never need to leave Omni to configure voice
- Retell's `display_position` on nodes is preserved, so the layout persists across sessions
- The `voice_agents` table in Omni DB is a thin pointer — source of truth lives in Retell
- New Retell agent types (when Retell adds them) will need new UI modes

## Alternatives Rejected

- **Dropdown to select existing Retell flows** — too passive, doesn't give users control over the flow graph
- **Embed Retell's own UI in an iframe** — not possible (no embeddable iframe from Retell)
- **Copy flow nodes into Omni DB** — creates sync problems; Retell is the source of truth
