You are an expert React/TypeScript and FastAPI engineer implementing a feature.

Here is the Round 7 spec:

---

## ROUND 7 — Retell Voice Node Editor: Data Correctness Fixes

---

### 1. OBJECTIVE

Fix three data-correctness bugs in the completed Retell voice node editor: a stale-position bug when editing dragged nodes, a publish payload that sends illegal extra fields to Retell, and a spurious `setNodes` mutation in `onConnect` that diverges node data from edge state.

---

### 2. FILES TO CHANGE

- `frontend/src/pages/RetellFlowEditor.tsx` — fix stale selectedNode position, onConnect mutation, unused import, publish payload
- `backend/app/routers/accounts.py` — fix `update_voice_agent_flow` to only forward allowed fields to Retell

### 3. DO NOT TOUCH

**CRITICAL: Do not touch any of these. Not even cosmetic changes.**

- `frontend/src/pages/Campaigns.tsx` — fully correct, do not open it
- `frontend/src/App.tsx` — route already registered correctly
- `backend/app/routers/accounts.py` — touch ONLY the `update_voice_agent_flow` endpoint body (lines ~246–268). Do not touch any other endpoint.
- Any file not listed in FILES TO CHANGE
- Existing node visual design (colors, sizing, typography) in RetellFlowEditor.tsx
- Existing `NodeConfigPanel` JSX
- Existing `CustomEdge` component
- The three custom node components (`ConversationNode`, `TransferCallNode`, `EndNode`)
- `retellNodesToFlow`, `retellEdgesToFlow` functions — do not modify them

---

### 4. IMPLEMENTATION

#### Fix A — Stale position bug in `RetellFlowEditor.tsx` (CRITICAL)

**Problem:** `selectedNode` is stored as a full `Node<RetellNode>` object in state. When the user drags a node, `onNodesChange` updates `nodes` but `selectedNode` still holds the pre-drag position. When `handleNodeChange` runs, it writes `{ ...updatedNode, position: <stale> }` back into `nodes`, silently resetting the node's position to where it was before the drag.

**Fix:** Replace the `selectedNode: Node<RetellNode> | null` state with a `selectedNodeId: string | null` state. Derive the actual selected node from `nodes` on every render using `useMemo`.

Exact changes to `RetellFlowEditor.tsx`:

**Step A1** — Replace the state declaration:
```ts
// REMOVE:
const [selectedNode, setSelectedNode] = useState<Node<RetellNode> | null>(null);

// ADD:
const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
const selectedNode = useMemo(
  () => (selectedNodeId ? nodes.find(n => n.id === selectedNodeId) ?? null : null),
  [nodes, selectedNodeId]
);
```

`useMemo` is already imported. No new imports needed.

**Step A2** — Update every call to `setSelectedNode(...)`:
- `setSelectedNode(node)` → `setSelectedNodeId(node.id)` (in `onNodeClick`)
- `setSelectedNode(null)` → `setSelectedNodeId(null)` (in `onPaneClick` and `onClose`)
- In `addNode`, after `setNodes(...)`: change `setSelectedNode(rfNode)` → `setSelectedNodeId(id)`
- In `RetellFlowInner` props, change `setSelectedNode` prop name to `setSelectedNodeId` and its type to `(id: string | null) => void`

**Step A3** — Update `handleNodeChange`:

```ts
// REMOVE:
const handleNodeChange = (updatedNode: Node<RetellNode>) => {
  setNodes(nds => nds.map(n => n.id === updatedNode.id ? updatedNode : n));
  setSelectedNode(updatedNode);
};

// ADD:
const handleNodeChange = useCallback((updatedNode: Node<RetellNode>) => {
  setNodes(nds => nds.map(n =>
    n.id === updatedNode.id
      ? { ...updatedNode, position: n.position }  // preserve drag position
      : n
  ));
}, [setNodes]);
```

Note: `setSelectedNode(updatedNode)` call is removed entirely — `selectedNode` is now derived, so no update needed.

**Step A4** — Update `RetellFlowInnerProps` interface: change `setSelectedNode: (n: Node<RetellNode> | null) => void` to `setSelectedNodeId: (id: string | null) => void`.

**Step A5** — In the `RetellFlowInner` function signature, rename the destructured prop `setSelectedNode` → `setSelectedNodeId`.

**Step A6** — In `RetellFlowInner` JSX:
- `onNodeClick={(_, node) => setSelectedNode(node)}` → `onNodeClick={(_, node) => setSelectedNodeId(node.id)}`
- `onPaneClick={() => setSelectedNode(null)}` → `onPaneClick={() => setSelectedNodeId(null)}`

**Step A7** — In the `NodeConfigPanel` delete handler (inside `RetellFlowInner`'s `onDelete`):
```ts
// REMOVE:
onDelete={() => {
  deleteElements({ nodes: [{ id: selectedNode.id }] });
  setSelectedNode(null);
}}

// ADD:
onDelete={() => {
  deleteElements({ nodes: [{ id: selectedNode.id }] });
  setSelectedNodeId(null);
}}
```

**Step A8** — In `RetellFlowEditor`'s `ReactFlowProvider` block, rename the prop:
```tsx
// REMOVE:
setSelectedNode={setSelectedNode}

// ADD:
setSelectedNodeId={setSelectedNodeId}
```

---

#### Fix B — Remove spurious `setNodes` in `onConnect` (`RetellFlowEditor.tsx`)

**Problem:** `onConnect` calls both `setEdges(addEdge(...))` AND `setNodes(nds => nds.map(...))` to add the new edge to `node.data.edges`. But `flowToRetellNodes` (called in `handlePublish`) builds each node's edges entirely from the ReactFlow `edges` state — it ignores `node.data.edges`. The `setNodes` update is therefore redundant AND can cause stale data bugs.

**Fix:** Remove the entire `setNodes(...)` call from `onConnect`. Keep only the `setEdges` call.

```ts
// REMOVE the entire setNodes block from onConnect:
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
```

The `onConnect` callback after the fix:
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

---

#### Fix C — Publish payload (`RetellFlowEditor.tsx`)

**Problem:** `handlePublish` spreads the full `flow` object into the PATCH body: `{ ...flow, global_prompt: globalPrompt, nodes: updatedNodes }`. The `flow` object contains `conversation_flow_id`, `created_at`, `last_modification_timestamp` and other fields the Retell PATCH endpoint does not accept. Retell only accepts `{ global_prompt, nodes, start_node_id }`.

**Fix:** Send only the three allowed fields:
```ts
// REMOVE:
await api.patch(`/accounts/voice/${agentId}/flow`, {
  ...flow,
  global_prompt: globalPrompt,
  nodes: updatedNodes
});

// ADD:
await api.patch(`/accounts/voice/${agentId}/flow`, {
  global_prompt: globalPrompt,
  nodes: updatedNodes,
  start_node_id: flow.start_node_id,
});
```

---

#### Fix D — Remove unused `useMemo` import if it's no longer used (`RetellFlowEditor.tsx`)

After Fix A, `useMemo` IS used (to derive `selectedNode`). No change needed to the import line — keep it.

---

#### Fix E — Backend publish filter (`backend/app/routers/accounts.py`)

**Problem:** `update_voice_agent_flow` receives `body: dict` and forwards it directly to Retell with `json=body`. If the frontend accidentally sends extra fields (e.g., `conversation_flow_id`), Retell may reject the request.

**Fix:** In the `update_voice_agent_flow` endpoint, extract only the three allowed fields before forwarding:

```python
# REPLACE the json=body line in update_voice_agent_flow:
payload = {k: v for k, v in body.items() if k in {"global_prompt", "nodes", "start_node_id"}}
resp = await client.patch(
    f"https://api.retellai.com/update-conversation-flow/{flow_id}",
    headers={"Authorization": f"Bearer {RETELL_API_KEY}"},
    json=payload,
)
```

This is a one-line whitelist filter. Change ONLY this — do not touch any other endpoint in `accounts.py`.

---

### 5. ACCEPTANCE CRITERIA

- [ ] Drag a node on the canvas, then open it in NodeConfigPanel and edit its name — after saving, the node stays at the dragged position (does not snap back to its original position)
- [ ] Adding a new edge via drag-connect does not mutate `node.data.edges` in the nodes state
- [ ] Clicking "Publish to Retell" sends exactly `{ global_prompt, nodes, start_node_id }` to the backend — verify in browser Network tab that the request body contains no `conversation_flow_id` or timestamp fields
- [ ] Backend `PATCH /accounts/voice/{agent_id}/flow` only forwards `global_prompt`, `nodes`, `start_node_id` to Retell — even if the client sends extra fields
- [ ] No TypeScript errors (`tsc --noEmit` passes)
- [ ] All existing canvas features in Campaigns.tsx remain fully functional — do NOT break them
- [ ] Standard mode prompt editing still works: select standard agent → fields load → edit → save → changes appear on next load
- [ ] Flow mode "Open Flow Editor →" button still navigates correctly
- [ ] The node/edge count still displays in flow mode ConfigSidebar

---

**GEMINI INSTRUCTIONS:**
- Read each file before editing — do not make blind edits
- Make surgical changes only — do not reformat, reorganize, or rename anything not listed above
- After all edits, run `tsc --noEmit` from `frontend/` and fix any TypeScript errors before finishing
- Do not add `console.log`, comments, or new abstractions
- Do not touch `Campaigns.tsx` under any circumstances

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now.