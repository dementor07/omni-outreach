You are the lead architect on a React/TypeScript + FastAPI project called Omni.
Your job: write a precise, actionable engineering task spec for Gemini CLI to implement.

GOAL: Build the Retell voice node editor: Standard mode shows editable begin_message + general_prompt in ConfigSidebar; Nested Flow mode opens a full ReactFlow sub-canvas at /campaigns/:id/voice-flow/:agentId where the Retell conversation flow nodes are editable and publishable back to Retell API

EXTRA CONTEXT FROM PREVIOUS ROUNDS:
Round 4 approved. Gemini output summary:
I will start by reading the content of `frontend/src/pages/RetellFlowEditor.tsx` to understand its current state and prepare for the requested changes.
I will check if `nanoid` is available in the project to decide whether to use it or `crypto.randomUUID()` for generating unique IDs.
I will check `frontend/package.json` to see if `nanoid` is listed as a dependency.
I will start by expanding the imports from `@xyflow/react` to include the additional components and types needed for custom edges and the node palette.
I will add the `CustomEdge` component to the file, placing it after the `EndNode` component and before the `nodeTypes` definition.
I will add the `retellEdgeTypes` and `retellDefaultEdgeOptions` constants after the `nodeTypes` definition.
I will update all occurrences of `type: 'default'` to `type: 'custom'` in the `retellEdgesToFlow` function and the `handleNodeChange` function to ensure consistency and proper rendering of custom edges.
I will now update the `ReactFlow` comp

[... truncated 10547 chars ...]

REPO STRUCTURE: The repo is at C:\Users\navij\Downloads\omni-outreach. Frontend is React 18 + TypeScript + Vite + Tailwind + @xyflow/react. Backend is FastAPI + asyncpg + PostgreSQL.

ADDITIONAL CONTEXT DOCUMENTS:


=== voice_node_retell_editor.md ===
# Voice Node — Retell Editor Context

## Goal
The voice node in the Omni canvas has a Standard / Nested Flow toggle. Build out both modes so the Config sidebar actually reads and writes to the Retell API live. No mock data, no local state only — everything persists to Retell.

## Current State

### Voice node in canvas (frontend/src/pages/Campaigns.tsx)
- ActionNode card shows a Simple/Flow mode badge (top-right pill)
- ConfigSidebar (`ConfigSidebar` component in same file) shows:
  - "Operation Mode" toggle (Standard / Nested Flow)
  - Voice Agent dropdown (from `/accounts/voice` — returns `[{id, name, retell_agent_id}]`)
  - When mode=flow: a "Retell Conversation Flow" dropdown (from `/accounts/voice/flows`)
- `retellFlowsQuery` is only enabled when mode=flow

### Backend (backend/app/routers/accounts.py)
- `GET /accounts/voice` — lists voice_agents table
- `GET /accounts/voice/flows` — proxies Retell `list-conversation-flows`
- Missing: get/update agent prompt, get/update conversation flow nodes

## Retell API Facts (live, verified)

### Standard agent (retell-llm type)
- Agent: `agent_e8c3a74b87a65dd27b7a121599` — "Omni Demo Agent"
- `response_engine: { type: "retell-llm", llm_id: "llm_31b0a17297ccb5441ada289bbc97" }`
- `GET https://api.retellai.com/get-retell-llm/{llm_id}` returns:
  ```json
  {
    "llm_id": "...",
    "general_prompt": "You are Hailey from Omni...",
    "begin_message": "Hey, hope I am not catching you at a terrible time — got a minute?",
    "model": "gpt-5.4"
  }
  ```
- `PATCH https://api.retellai.com/update-retell-llm/{llm_id}` with `{ general_prompt, begin_message }` to save

### Nested Flow agent (conversation-flow type)
- Agent: `agent_095ac4237a4d6ed7f8c86b6d39` — "Omni Demo v2 (conversation flow)"
- `response_engine: { type: "conversation-flow", conversation_flow_id: "conversation_flow_80c3117c2c32" }`
- `GET https://api.retellai.com/get-conversation-flow/{conversation_flow_id}` returns:
  ```json
  {
    "conversation_flow_id": "...",
    "global_prompt": "You are Hailey from Omni...",
    "start_node_id": "node-opener",
    "nodes": [
      {
        "id": "node-opener",
        "type": "conversation",
        "name": "Opener",
        "display_position": { "x": 100, "y": 100 },
        "instruction": { "type": "prompt", "text": "Say: ..." },
        "edges": [
          { "id": "edge-o1", "destination_node_id": "node-pivot", "transition_condition": { "type": "prompt", "prompt": "They respond about outbound" } }
        ]
      },
      {
        "id": "node-transfer",
        "type": "transfer_call",
        "name": "Transfer",
        "transfer_destination": { "type": "predefined", "number": "+918129244426" },
        "instruction": { "type": "prompt", "text": "Say: looping them in..." },
        "transfer_option": { "type": "cold_transfer", "enable_bridge_audio_cue": true },
        "edge": { "id": "edge-t1", "destination_node_id": "node-end", "transition_condition": { "type": "prompt", "prompt": "Transfer failed" } }
      },
      {
        "id": "node-end",
        "type": "end",
        "name": "End Call",
        "instruction": { "type": "prompt", "text": "End the call warmly." }
      }
    ]
  }
  ```
- `PATCH https://api.retellai.com/update-conversation-flow/{id}` with `{ global_prompt, nodes, start_node_id }` to save

### Getting agent details (to know its type + llm_id / flow_id)
- `GET https://api.retellai.com/get-agent/{retell_agent_id}` returns full agent including `response_engine`

## What Needs to Be Built

### Phase 1 — Standard Mode (simpler, do first)
When mode=standard and agent is selected:
1. Backend: `GET /accounts/voice/{agent_id}/prompt` — fetch agent from Retell, resolve llm_id, fetch LLM, return `{ begin_message, general_prompt, llm_id, model }`
2. Backend: `PATCH /accounts/voice/{agent_id}/prompt` — body `{ begin_message, general_prompt }`, PATCH Retell LLM
3. Frontend ConfigSidebar: below agent dropdown in standard mode, show:
   - "Begin Message" short text input
   - "System Prompt" tall textarea (min 200px)
   - "Save Prompt" button → calls PATCH endpoint
   - Load state from GET endpoint when agent is selected

### Phase 2 — Nested Flow Mode (the sub-canvas)
When mode=flow and agent is selected:
1. Backend: `GET /accounts/voice/{agent_id}/flow` — fetch agent, resolve conversation_flow_id, fetch flow, return full flow JSON
2. Backend: `PATCH /accounts/voice/{agent_id}/flow` — body is the full flow JSON, PATCH Retell conversation-flow

3. Frontend — new page/route: `RetellFlowEditor` at `/campaigns/:campaignId/voice-flow/:agentId`
   - Full-screen ReactFlow canvas (re-use same @xyflow/react setup as Campaigns.tsx)
   - Node types:
     - `conversation` node: grey card, shows name + first 60 chars of instruction.text
     - `transfer_call` node: indigo card, shows name + phone number
     - `end` node: red/rose card, shows "End Call"
   - Edges: labeled with `transition_condition.prompt` (truncated to 40 chars)
   - Top-right panel: "Global Prompt" textarea + Save button
   - Clicking a node opens right-side ConfigPanel (like Omni's existing ConfigSidebar pattern):
     - conversation: name input, instruction textarea, list of outgoing edges (each with condition textarea + destination selector)
     - transfer_call: name input, phone number input, instruction textarea
     - end: name input, instruction textarea
   - "Add Node" palette at bottom: add conversation / transfer / end node
   - Custom deletable edges (re-use existing CustomEdge pattern from Campaigns.tsx)
   - "Publish to Retell" button → PATCH /accounts/voice/{agentId}/flow → toast success

4. Frontend — ConfigSidebar in Campaigns.tsx for voice node in flow mode:
   - Instead of dropdown of flows, show "Open Flow Editor →" button
   - On click: navigate to `/campaigns/:campaignId/voice-flow/:agentId`
   - Below button: show node count if flow loaded (e.g. "8 nodes · 12 edges")

## Design System Rules (CRITICAL — Gemini always gets these wrong)
- Colors: `slate-*`, `sky-*`, `emerald-*`, `rose-*`, `indigo-*` — NO `gray-*`, `blue-*`, `green-*`, `red-*`
- API client: `import api from '../api/client'` — has Bearer token interceptors. NEVER use raw fetch/axios
- Toast: `import { useToast } from '../components/Toast'` then `const toast = useToast()` then `toast.success()` / `toast.error()`
- No `React.FC` — use plain function components with interface props
- Default exports for pages, named exports for components
- No wrapper `p-6 max-w-5xl mx-auto` — Layout already provides padding
- Route registration: `frontend/src/App.tsx` (inside `RequireAuth`)
- Sidebar nav: `frontend/src/components/Sidebar.tsx` — only add nav items if it's a top-level page

## Files to Change
- `backend/app/routers/accounts.py` — add prompt + flow GET/PATCH endpoints
- `frontend/src/pages/Campaigns.tsx` — update ConfigSidebar voice section for both modes
- `frontend/src/pages/RetellFlowEditor.tsx` — NEW: full sub-canvas editor
- `frontend/src/App.tsx` — add route for RetellFlowEditor
- Do NOT touch: `sequencer.py`, `dispatcher.py`, `SequentialBuilder.tsx`, any non-voice parts of Campaigns.tsx

## Acceptance Criteria
- [ ] Standard mode: select agent → begin message + prompt load from Retell → edit → save → changes persist in Retell
- [ ] Nested Flow mode: ConfigSidebar shows "Open Flow Editor →" + node/edge count
- [ ] /campaigns/:id/voice-flow/:agentId renders the flow as a draggable ReactFlow graph
- [ ] Clicking a node opens right-side config panel with editable fields
- [ ] "Publish to Retell" saves the full graph back via PATCH
- [ ] Retell's display_position is preserved (nodes don't jump on reload)
- [ ] No TypeScript errors
- [ ] No existing canvas features broken


Write a spec with these sections:
1. OBJECTIVE — one sentence
2. FILES TO CHANGE — exact file paths
3. DO NOT TOUCH — files/features Gemini must not modify
4. IMPLEMENTATION — step by step, with exact function names, component names, types
5. ACCEPTANCE CRITERIA — bullet list of what done looks like

Be extremely precise. Gemini tends to over-engineer and strip existing features — warn it explicitly.
Do NOT include any preamble. Start directly with the spec.