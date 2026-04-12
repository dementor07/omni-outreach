# Round 6 — Bug-Fix Pass on Retell Voice Node Editor

## 1. OBJECTIVE

Fix five correctness bugs introduced or left over from rounds 1-5 in the Retell voice node editor: two TypeScript errors, one stale-state display bug, one dead-code side-effect in `onConnect`, and one backend serialization error that sends forbidden read-only fields to the Retell PATCH API.

---

## 2. FILES TO CHANGE

| File | What changes |
|---|---|
| `frontend/src/pages/RetellFlowEditor.tsx` | Remove unused imports; remove dead `setNodes` call in `onConnect`; fix `handlePublish` payload |
| `frontend/src/pages/Campaigns.tsx` | Clear `agentPrompt` before fetching; remove `toast` from `useEffect` deps |
| `backend/app/routers/accounts.py` | Fix `update_voice_agent_flow` to only forward allowed fields to Retell |

---

## 3. DO NOT TOUCH

- `frontend/src/pages/RetellFlowEditor.tsx` — do NOT rewrite any component, type, or logic that is not listed in the fix steps below. Every node component (`ConversationNode`, `TransferCallNode`, `EndNode`), `NodeConfigPanel`, `RetellFlowInner`, `CustomEdge`, all conversion helpers (`retellNodesToFlow`, `retellEdgesToFlow`, `flowToRetellNodes`), and the `RetellFlowEditor` page component must stay byte-for-byte identical except for the three targeted fixes listed in §4.
- `frontend/src/pages/Campaigns.tsx` — do NOT touch anything outside the voice section inside `ConfigSidebar`. The canvas, node rendering, `SequentialBuilder`, `ActionNode`, template section, `emailAccountsQuery`, and all non-voice state must remain untouched.
- `backend/app/routers/accounts.py` — do NOT modify `get_voice_agent_flow`, `get_voice_agent_prompt`, `update_voice_agent_prompt`, `list_voice_agents`, `create_voice_agent`, `delete_voice_agent`, or `list_retell_flows`. Only `update_voice_agent_flow` needs to change.
- `frontend/src/App.tsx` — do NOT touch.
- `frontend/src/components/Sidebar.tsx` — do NOT touch.
- `backend/app/routers/sequencer.py`, `dispatcher.py` — do NOT touch.
- `frontend/src/pages/SequentialBuilder.tsx` — do NOT touch.

---

## 4. IMPLEMENTATION

### Fix A — Remove unused imports in `RetellFlowEditor.tsx` [TypeScript error]

**File:** `frontend/src/pages/RetellFlowEditor.tsx`

The top-level import from `'@xyflow/react'` currently includes `useMemo` (from React) and `ConnectionLineType` (from @xyflow/react). Neither is used anywhere in the file. With `noUnusedLocals: true` in tsconfig this causes a build error.

**Step A1.** In the React import line at line 1, remove `useMemo` from the import list.

Before:
```ts
import { useState, useCallback, useEffect, useMemo } from 'react';
```
After:
```ts
import { useState, useCallback, useEffect } from 'react';
```

**Step A2.** In the `@xyflow/react` import block (lines 3–28), remove `ConnectionLineType` from the named imports. Do not remove any other import from that block.

Verify: run `grep -n "useMemo\|ConnectionLineType" frontend/src/pages/RetellFlowEditor.tsx` and confirm zero matches.

---

### Fix B — Remove dead `setNodes` call in `onConnect` [dead code / dual source of truth]

**File:** `frontend/src/pages/RetellFlowEditor.tsx`

After Round 5, `NodeConfigPanel` and `flowToRetellNodes` both treat `rfEdges` (the ReactFlow edge state) as the single source of truth for outgoing edges. The `onConnect` handler still has a `setNodes` call that writes the new edge back into `n.data.edges`. This is dead code — it is never read during serialization or rendering — and it creates a confusing dual state.

**Current `onConnect` (lines 464–490):**
```ts
const onConnect = useCallback(
  (params: Connection) => {
    const newRetellEdge: RetellEdge = {
      id: `edge-${Date.now()}`,
      destination_node_id: params.target!,
      transition_condition: { type: 'prompt', prompt: '' },
    };
    setEdges((eds) =>
      addEdge({ ...params, id: newRetellEdge.id, data: newRetellEdge, label: '' }, eds)
    );
    setNodes((nds) =>
      nds.map((n) => {
        if (n.id === params.source && n.data.type === 'conversation') {
          return {
            ...n,
            data: {
              ...n.data,
              edges: [...(n.data.edges ?? []), newRetellEdge],
            },
          };
        }
        return n;
      })
    );
  },
  [setEdges, setNodes]
);
```

**Replace with:**
```ts
const onConnect = useCallback(
  (params: Connection) => {
    const newRetellEdge: RetellEdge = {
      id: `edge-${Date.now()}`,
      destination_node_id: params.target!,
      transition_condition: { type: 'prompt', prompt: '' },
    };
    setEdges((eds) =>
      addEdge({ ...params, id: newRetellEdge.id, data: newRetellEdge, label: '' }, eds)
    );
  },
  [setEdges]
);
```

Remove `setNodes` from the dependency array too. Do not change the `addEdge` call or `newRetellEdge` construction.

---

### Fix C — Fix `handlePublish` payload [backend serialization bug, frontend side]

**File:** `frontend/src/pages/RetellFlowEditor.tsx`

`handlePublish` currently spreads the entire `flow` object into the PATCH body:
```ts
await api.patch(`/accounts/voice/${agentId}/flow`, {
  ...flow,
  global_prompt: globalPrompt,
  nodes: updatedNodes
});
```

`flow` contains `conversation_flow_id` and other read-only fields returned by Retell's GET endpoint. Sending them back in the PATCH body causes Retell to return a 422. Only `global_prompt`, `nodes`, and `start_node_id` are mutable.

**Replace `handlePublish` body with:**
```ts
const handlePublish = async () => {
  if (!flow) return;
  setSaving(true);
  try {
    const updatedNodes = flowToRetellNodes(nodes, edges);
    await api.patch(`/accounts/voice/${agentId}/flow`, {
      global_prompt: globalPrompt,
      nodes: updatedNodes,
      start_node_id: flow.start_node_id,
    });
    toast.success('Flow published to Retell');
  } catch {
    toast.error('Failed to publish flow');
  } finally {
    setSaving(false);
  }
};
```

Do not change anything else in the component.

---

### Fix D — Fix `update_voice_agent_flow` to forward only allowed fields [backend serialization bug]

**File:** `backend/app/routers/accounts.py`

`update_voice_agent_flow` currently receives a raw `dict` from the frontend and forwards it entirely to Retell's PATCH endpoint. Even after Fix C, the backend is the correct place to enforce the allowed-field list defensively.

**Current endpoint (lines 246–262 approximately):**
```python
@router.patch("/voice/{agent_id}/flow")
async def update_voice_agent_flow(agent_id: str, body: dict, user_id: str = Depends(get_current_user)):
    agent = await fetch_one("SELECT retell_agent_id FROM voice_agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Voice agent not found")

    agent_data = await _get_retell_agent(agent["retell_agent_id"])
    engine = agent_data.get("response_engine")
    if not engine or engine.get("type") != "conversation-flow":
        raise HTTPException(status_code=400, detail="Agent is not a conversation-flow agent")

    flow_id = engine["conversation_flow_id"]
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"https://api.retellai.com/update-conversation-flow/{flow_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
            json=body,
        )
        if not resp.is_success:
            raise HTTPException(status_code=resp.status_code, detail=resp.text)

        return {"success": True}
```

**Replace only the `json=body` line** with an allow-list extract:

```python
    payload = {
        k: body[k]
        for k in ("global_prompt", "nodes", "start_node_id")
        if k in body
    }
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.patch(
            f"https://api.retellai.com/update-conversation-flow/{flow_id}",
            headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
            json=payload,
        )
```

Do not change the function signature, the auth check, the agent lookup, or the response.

---

### Fix E — Clear stale `agentPrompt` when switching agents [UI bug]

**File:** `frontend/src/pages/Campaigns.tsx`

When the user switches from agent A to agent B in standard mode, the old `agentPrompt` (agent A's data) stays visible in the inputs until agent B's API response arrives. This makes it look like agent B has agent A's prompt.

**Locate the useEffect that loads the prompt** — it starts with:
```ts
useEffect(() => {
  if (mode !== 'standard' || !selectedVoiceAgentId) return;
  setPromptLoading(true);
  api.get(`/accounts/voice/${selectedVoiceAgentId}/prompt`)
    .then(r => setAgentPrompt(r.data))
    .catch(() => toast.error('Failed to load agent prompt'))
    .finally(() => setPromptLoading(false));
}, [selectedVoiceAgentId, mode, toast]);
```

**Replace with:**
```ts
useEffect(() => {
  if (mode !== 'standard' || !selectedVoiceAgentId) return;
  setAgentPrompt(null);
  setPromptLoading(true);
  api.get(`/accounts/voice/${selectedVoiceAgentId}/prompt`)
    .then(r => setAgentPrompt(r.data))
    .catch(() => toast.error('Failed to load agent prompt'))
    .finally(() => setPromptLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
}, [selectedVoiceAgentId, mode]);
```

Two changes:
1. Add `setAgentPrompt(null)` as the first line so stale data clears immediately.
2. Remove `toast` from the dependency array and add the eslint-disable comment on the line before the closing bracket. `toast` is a stable singleton — including it in deps causes React's exhaustive-deps lint rule to mark it as a warning on every re-render in some versions of `useToast`. Remove it from the dep array only; do not change the `toast.error(...)` call.

Do not touch any other `useEffect` in `ConfigSidebar`.

---

## 5. ACCEPTANCE CRITERIA

- `npx tsc --noEmit` in `frontend/` exits with zero errors (specifically: no "unused variable" errors for `useMemo` or `ConnectionLineType`).
- Switching between two standard-mode voice agents in ConfigSidebar immediately clears the prompt fields (shows skeleton loader, not the previous agent's text).
- Connecting two nodes on the RetellFlowEditor canvas does not call `setNodes` — verified by adding a temporary `console.log` inside the old branch and confirming it never fires.
- Clicking "Publish to Retell" sends a PATCH body of exactly `{ global_prompt, nodes, start_node_id }` — no `conversation_flow_id` or other Retell read-only fields present (verify in browser Network tab).
- The backend `update_voice_agent_flow` function forwards only the three allowed keys to Retell; any extra keys in the request body are silently dropped.
- All existing canvas functionality in Campaigns.tsx (email, delay, LinkedIn nodes, template editor, SequentialBuilder) continues to work — no regression.
- No new `console.log` statements are left in any modified file.
