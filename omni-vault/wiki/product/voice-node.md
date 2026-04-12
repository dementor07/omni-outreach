---
title: Voice Node
category: product
tags: [voice, canvas, retell, UX, ConfigSidebar]
sources: []
updated: 2026-04-12
---

# Voice Node

The voice node (`action_voice`) in the Omni canvas triggers an AI phone call to the lead via [[retell-integration]].

## Canvas Card

Shows:
- Phone icon (indigo)
- Mode badge: Simple / Flow pill (top-right)
- Status: Ready / Draft

## Config Panel (ConfigSidebar)

### Standard Mode
- Agent selector dropdown (from `GET /accounts/voice`)
- Begin Message — short text input
- System Prompt — tall textarea
- Save → `PATCH /accounts/voice/{agent_id}/prompt` → writes to Retell LLM

### Nested Flow Mode
- Agent selector dropdown
- "Open Flow Editor →" button → navigates to `/campaigns/:id/voice-flow/:agentId`
- Shows node/edge count of the current flow

## Retell Flow Editor (`RetellFlowEditor.tsx`)

Full-screen sub-canvas at `/campaigns/:campaignId/voice-flow/:agentId`.

Node types rendered as ReactFlow nodes:
- `conversation` — grey card, name + script preview
- `transfer_call` — indigo card, name + phone number
- `end` — rose card

Edges labeled with transition condition (truncated).

Right-side config panel when node selected:
- `conversation`: name, instruction script, outgoing edges with condition + destination
- `transfer_call`: name, phone number, instruction
- `end`: name, instruction

Top bar: Global Prompt textarea + "Publish to Retell" button → `PATCH /accounts/voice/{agentId}/flow`

## Design Decision

The Standard/Nested Flow toggle maps directly to Retell's two agent architectures (`retell-llm` vs `conversation-flow`). This is intentional — Omni's canvas becomes the editor for Retell's flow graph, embedding one nodal system inside another.

See [[decisions/voice-node-architecture]] for the ADR.

## Related Pages
- [[retell-integration]]
- [[canvas-editor]]
- [[sequence-engine]]
