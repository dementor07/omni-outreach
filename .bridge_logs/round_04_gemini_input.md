You are an expert React/TypeScript and FastAPI engineer implementing a feature.

Now I have everything I need. Here is the Round 4 spec:

---

## ROUND 04 — Retell Voice Node Editor: Bug Fixes & Verification

---

### 1. OBJECTIVE

Fix three data-correctness bugs in `RetellFlowEditor.tsx` that send wrong type literals to the Retell API, and verify the full feature compiles and runs end-to-end.

---

### 2. FILES TO CHANGE

```
frontend/src/pages/RetellFlowEditor.tsx   ← 3 targeted bug fixes only
```

---

### 3. DO NOT TOUCH

- `backend/app/routers/accounts.py` — all four Retell endpoints (`GET/PATCH /voice/{id}/prompt`, `GET/PATCH /voice/{id}/flow`) are complete and correct. **Do not modify.**
- `frontend/src/App.tsx` — route `/campaigns/:id/voice-flow/:agentId` → `<RetellFlowEditor />` is already registered. **Do not modify.**
- `frontend/src/pages/Campaigns.tsx` — ConfigSidebar voice section is fully implemented: Standard mode loads/saves begin_message + general_prompt, Flow mode shows "Open Flow Editor →" + node/edge count. **Do not modify any part of this file.**
- `frontend/src/api/client.ts` — `api` is a named export (`export const api`). The import in `RetellFlowEditor.tsx` (`import { api } from '../api/client'`) is correct. **Do not modify.**
- Every other file in the repo.

---

### 4. IMPLEMENTATION

Read `frontend/src/pages/RetellFlowEditor.tsx` in full before making any change. Apply only these three surgical edits:

---

#### Fix 1 — Wrong `instruction.type` literal (breaks Retell PATCH)

**Location:** `NodeConfigPanel` component, inside the "Instructions" `<textarea>` `onChange` handler.

**Current (wrong):**
```typescript
onChange={(e) => updateData({ instruction: { type: 'text', text: e.target.value } })}
```

**Corrected:**
```typescript
onChange={(e) => updateData({ instruction: { type: 'prompt', text: e.target.value } })}
```

The Retell API `instruction` object requires `type: 'prompt'`. Sending `type: 'text'` will cause Retell to reject the PATCH with a 422.

---

#### Fix 2 — Wrong `transfer_destination.type` literal (breaks Retell PATCH)

**Location:** `NodeConfigPanel` component, inside the `transfer_call` branch, the "Phone Number" `<input>` `onChange` handler.

**Current (wrong):**
```typescript
onChange={(e) => updateData({ transfer_destination: { type: 'number', number: e.target.value } })}
```

**Corrected:**
```typescript
onChange={(e) => updateData({ transfer_destination: { type: 'predefined', number: e.target.value } })}
```

The Retell API `transfer_destination` object requires `type: 'predefined'`. Sending `type: 'number'` will cause Retell to reject the PATCH with a 422.

---

#### Fix 3 — `onConnect` creates edges without `data`, so newly-drawn edges have no `RetellEdge` structure

**Location:** The `onConnect` `useCallback` in the `RetellFlowEditor` function body.

**Current (broken):**
```typescript
const onConnect = useCallback(
  (params: Connection) => setEdges((eds) => addEdge(params, eds)),
  [setEdges]
);
```

**Corrected:**
```typescript
const onConnect = useCallback(
  (params: Connection) => {
    const edgeId = `edge-${params.source}-${params.target}-${Date.now()}`;
    const newEdge: Edge<RetellEdge> = {
      id: edgeId,
      source: params.source!,
      target: params.target!,
      sourceHandle: params.sourceHandle ?? null,
      targetHandle: params.targetHandle ?? null,
      type: 'custom',
      label: '',
      data: {
        id: edgeId,
        destination_node_id: params.target!,
        transition_condition: { type: 'prompt', prompt: '' },
      },
    };
    setEdges((eds) => addEdge(newEdge, eds));
  },
  [setEdges]
);
```

Without this fix, edges drawn by the user on the canvas have no `data.id` and no `transition_condition`. The `flowToRetellNodes` function falls back to `e.label` (empty string) for the condition — the edge is sent to Retell with an empty condition and an auto-generated ID like `node-opener-node-pivot`, which is ambiguous and may collide on re-connect.

---

#### No other changes

Do **not** refactor, reorganize, rename, or add any code beyond these three targeted edits. Do not add comments, docstrings, or type annotations to surrounding code. Do not touch the node card components (`ConversationNode`, `TransferCallNode`, `EndNode`), `flowToRetellNodes`, `retellNodesToFlow`, `retellEdgesToFlow`, the `NodeConfigPanel` structure, the `addNode` function, the header, or the `ReactFlow` render tree.

---

### 5. ACCEPTANCE CRITERIA

- [ ] `RetellFlowEditor.tsx` has no TypeScript errors (`tsc --noEmit` passes)
- [ ] Vite dev build starts without error (`npm run dev` in `frontend/`)
- [ ] Standard mode: selecting a voice agent in ConfigSidebar loads `begin_message` and `general_prompt` from `GET /accounts/voice/{id}/prompt`; editing and clicking "Save Prompt" sends a `PATCH` and shows a success toast
- [ ] Flow mode ConfigSidebar: "Open Flow Editor →" button navigates to `/campaigns/:id/voice-flow/:agentId`; node/edge count label appears below the button once loaded
- [ ] `/campaigns/:id/voice-flow/:agentId` renders the Retell flow as a draggable ReactFlow graph with correct node colors (slate for `conversation`, indigo for `transfer_call`, rose for `end`)
- [ ] Clicking a node opens `NodeConfigPanel`; name and instruction fields are editable
- [ ] Editing a `transfer_call` node's phone number and publishing sends `transfer_destination: { type: 'predefined', number: '...' }` to Retell — **not** `type: 'number'`
- [ ] Editing any node's instruction and publishing sends `instruction: { type: 'prompt', text: '...' }` to Retell — **not** `type: 'text'`
- [ ] Drawing a new connection between two nodes (drag from source handle to target handle) creates an edge with a stable `id`, `type: 'custom'`, and `transition_condition: { type: 'prompt', prompt: '' }` in `data`
- [ ] "Publish to Retell" button calls `PATCH /accounts/voice/{agentId}/flow`, shows "Flow published to Retell" toast on success
- [ ] "Back to Sequence" navigates to `/campaigns/:campaignId`
- [ ] No existing Campaigns canvas features are broken (email, LinkedIn, delay nodes unaffected)

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now.