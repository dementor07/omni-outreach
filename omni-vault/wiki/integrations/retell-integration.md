---
title: Retell AI Integration
category: integrations
tags: [retell, voice, AI, conversation-flow, retell-llm]
sources: []
updated: 2026-04-12
---

# Retell AI Integration

Retell AI powers the voice call channel in Omni. It supports two agent architectures.

## Agent Types

### Standard (`retell-llm`)
- Single global prompt — freeform LLM-driven conversation
- No predetermined flow — agent improvises based on prompt
- Config: `general_prompt` + `begin_message`
- API: `GET /get-retell-llm/{llm_id}`, `PATCH /update-retell-llm/{llm_id}`
- Live agent: "Omni Demo Agent" (`agent_e8c3a74b87a65dd27b7a121599`, llm: `llm_31b0a17297ccb5441ada289bbc97`)

### Nested Flow (`conversation-flow`)
- Nodal graph of conversation states — deterministic branching
- Each node: `conversation | transfer_call | end`
- Edges have `transition_condition.prompt` — LLM decides when to transition
- Nodes store `display_position {x, y}` — positions persist in Retell
- API: `GET /get-conversation-flow/{id}`, `PATCH /update-conversation-flow/{id}`
- Live agent: "Omni Demo v2" (`agent_095ac4237a4d6ed7f8c86b6d39`, flow: `conversation_flow_80c3117c2c32`)

## Live Flow Structure (as of 2026-04-12)

Nodes: Opener → The Product → The Reveal → The Close → Transfer / End
Objection handling: Not Interested → re-pivots to The Product
Busy: schedules callback

Transfer destination: `+918129244426` (cold transfer)

## Omni DB

`voice_agents` table: `id, retell_agent_id, name, is_active`
- Maps Omni's internal UUID to Retell's agent ID
- Source of truth for agent details lives in Retell, not Omni DB

## API Key
Stored in server `.env` as `RETELL_API_KEY`. Base URL: `https://api.retellai.com`

## Voice Node in Canvas
The voice node in the [[canvas-editor]] has two modes (toggle in the ConfigSidebar):

- **Standard** — ConfigSidebar shows the `begin_message` + global-prompt editor for the `retell-llm`. Saves via `PATCH /update-retell-llm/{llm_id}`.
- **Nested Flow** — clicking the node navigates to a sub-canvas at `/campaigns/:id/voice-flow/:agentId` rendered by `RetellFlowEditor.tsx`. The sub-canvas reads and writes the live Retell conversation-flow graph directly.

Inside `RetellFlowEditor`:

- Each Retell node (`conversation`, `transfer_call`, `end`) has its own right-side config panel. `conversation` exposes the instruction script and the outgoing edges with their transition conditions; `transfer_call` exposes the destination phone number; `end` exposes a final instruction.
- Edges show their transition condition labels (truncated for display).
- The top bar has a **Global Prompt** textarea and a **Publish to Retell** button. The button maps to `PATCH /accounts/voice/{agentId}/flow`, which forwards to Retell's `update-conversation-flow` endpoint. Until Publish is clicked, edits are local-only.

## Calling

`POST https://api.retellai.com/v2/create-phone-call` with:
- `from_number`: `+16626425896`
- `to_number`: lead's phone
- `agent_id`: retell_agent_id
- `metadata`: `{ lead_id, campaign_id }`

## Related Pages
- [[canvas-editor]]
- [[voice-node-architecture]]
- [[system-overview]]
- [[channels]]
