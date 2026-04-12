You are an expert React/TypeScript and FastAPI engineer implementing a feature.

I now have a complete picture of the codebase. Here's the Round 5 spec:

---

## ROUND 5 ENGINEERING SPEC — Retell Voice Node Editor: Edge Sync Fix + Polish

---

### 1. OBJECTIVE

Fix the canvas↔NodeConfigPanel edge desync bug in `RetellFlowEditor.tsx` (canvas-drawn edges are invisible in the config panel and get deleted when node data is edited), and auto-open the NodeConfigPanel when a node is added via the palette.

---

### 2. FILES TO CHANGE

- `frontend/src/pages/RetellFlowEditor.tsx` — only file to touch

---

### 3. DO NOT TOUCH

- `backend/app/routers/accounts.py` — all 4 endpoints are fully implemented and working
- `frontend/src/pages/Campaigns.tsx` — ConfigSidebar voice section is complete; do NOT modify
- `frontend/src/App.tsx` — route is already registered at line 35
- `frontend/src/api/client.ts` — do not change imports or auth logic
- `frontend/src/components/Toast.tsx` — do not modify
- Any non-voice node type in `Campaigns.tsx` (email, LinkedIn, delay)
- `SequentialBuilder.tsx`, `sequencer.py`, `dispatcher.py`

The `api` client is a **named export**: `import { api } from '../api/client'` — this is already correct in the file, do NOT change it to a default import.

---

### 4. IMPLEMENTATION

#### Context: The Bug

`NodeConfigPanel` currently reads outgoing edge data from `node.data.edges` (Retell-format edges stored in node data). But `onConnect` only writes to the ReactFlow `edges` state — it does NOT update `node.data.edges`. This means:

- **Drawing a canvas edge**: never appears in NodeConfigPanel's "Outgoing Edges" list
- **Editing any field in NodeConfigPanel**: the `handleNodeChange` function rebuilds ReactFlow `edges` from `data.edges`, silently deleting any canvas-drawn edges not yet reflected in `data.edges`

The fix: make ReactFlow `edges` the **single source of truth**. NodeConfigPanel must read from `rfEdges` and write back to `rfEdges`.

---

#### Step 1 — Update `NodeConfigPanel` props interface

Replace the current props interface:

```typescript
// CURRENT (lines ~207-214):
function NodeConfigPanel({
  node,
  allNodes,
  onChange,
  onClose
}: {
  node: Node<RetellNode>;
  allNodes: Node<RetellNode>[];
  onChange: (updated: Node<RetellNode>) => void;
  onClose: () => void;
})
```

With:

```typescript
function NodeConfigPanel({
  node,
  allNodes,
  edges,
  onChange,
  onEdgeUpdate,
  onEdgeDestinationChange,
  onClose,
}: {
  node: Node<RetellNode>;
  allNodes: Node<RetellNode>[];
  edges: Edge<RetellEdge>[];
  onChange: (updated: Node<RetellNode>) => void;
  onEdgeUpdate: (edgeId: string, condition: { type: string; prompt: string }) => void;
  onEdgeDestinationChange: (edgeId: string, destinationNodeId: string) => void;
  onClose: () => void;
})
```

---

#### Step 2 — Fix "Outgoing Edges" section in `NodeConfigPanel`

Replace the `data.type === 'conversation'` block (currently at lines ~262-298) with:

```typescript
{data.type === 'conversation' && (
  <div className="space-y-4 pt-4 border-t border-slate-800">
    <h4 className="text-[9px] font-black uppercase tracking-widest text-slate-500">Outgoing Edges</h4>
    {edges.filter(e => e.source === node.id).map((edge) => (
      <div key={edge.id} className="p-3 bg-slate-800/50 rounded-xl border border-slate-700/50 space-y-3">
        <div>
          <label className="text-[8px] font-bold uppercase text-slate-600 mb-1 block">Condition</label>
          <textarea
            value={edge.data?.transition_condition?.prompt || ''}
            onChange={(e) => onEdgeUpdate(edge.id, { type: 'prompt', prompt: e.target.value })}
            className="w-full bg-slate-900 border-none rounded-lg px-2 py-1.5 text-[11px] text-slate-300 focus:ring-1 focus:ring-sky-500 outline-none resize-none"
          />
        </div>
        <div>
          <label className="text-[8px] font-bold uppercase text-slate-600 mb-1 block">Destination</label>
          <select
            value={edge.target}
            onChange={(e) => onEdgeDestinationChange(edge.id, e.target.value)}
            className="w-full bg-slate-900 border-none rounded-lg px-2 py-1.5 text-[11px] text-slate-300 focus:ring-1 focus:ring-sky-500 outline-none"
          >
            {allNodes.map((n) => (
              <option key={n.id} value={n.id}>{n.data.name} ({n.id.slice(0, 4)})</option>
            ))}
          </select>
        </div>
      </div>
    ))}
  </div>
)}
```

Key changes: `(data.edges || []).map(...)` → `edges.filter(e => e.source === node.id).map(...)`. Condition reads `edge.data?.transition_condition?.prompt`. Destination reads `edge.target`. Both changes go through new callbacks instead of `updateData`.

---

#### Step 3 — Remove the broken edge sync from `handleNodeChange`

In the `handleNodeChange` function (currently lines ~372-392), **delete the entire `if (updatedNode.data.type === 'conversation')` block**:

```typescript
// DELETE this entire block from handleNodeChange:
if (updatedNode.data.type === 'conversation') {
  const nodeData = updatedNode.data;
  setEdges(eds => {
    const otherEdges = eds.filter(e => e.source !== updatedNode.id);
    const nodeEdges = (nodeData.edges || []).map(e => ({
      id: e.id,
      source: updatedNode.id,
      target: e.destination_node_id,
      label: e.transition_condition?.prompt?.slice(0, 40) ?? '',
      type: 'custom',
      data: e
    }));
    return [...otherEdges, ...nodeEdges];
  });
}
```

After deletion, `handleNodeChange` should only do:

```typescript
const handleNodeChange = (updatedNode: Node<RetellNode>) => {
  setNodes(nds => nds.map(n => n.id === updatedNode.id ? updatedNode : n));
  setSelectedNode(updatedNode);
};
```

---

#### Step 4 — Implement `onEdgeUpdate` and `onEdgeDestinationChange` in `RetellFlowEditor`

Add these two callbacks in `RetellFlowEditor` (after the `handleNodeChange` function):

```typescript
const handleEdgeUpdate = useCallback((edgeId: string, condition: { type: string; prompt: string }) => {
  setEdges(eds => eds.map(e =>
    e.id === edgeId
      ? { ...e, label: condition.prompt.slice(0, 40), data: { ...e.data!, transition_condition: condition } }
      : e
  ));
}, [setEdges]);

const handleEdgeDestinationChange = useCallback((edgeId: string, destinationNodeId: string) => {
  setEdges(eds => eds.map(e =>
    e.id === edgeId
      ? { ...e, target: destinationNodeId, data: { ...e.data!, destination_node_id: destinationNodeId } }
      : e
  ));
}, [setEdges]);
```

---

#### Step 5 — Pass new props to `NodeConfigPanel` in JSX

Find the `<NodeConfigPanel` usage at the bottom of the return (currently lines ~510-517) and add the new props:

```typescript
{selectedNode && (
  <NodeConfigPanel
    node={selectedNode}
    allNodes={nodes}
    edges={edges}
    onChange={handleNodeChange}
    onEdgeUpdate={handleEdgeUpdate}
    onEdgeDestinationChange={handleEdgeDestinationChange}
    onClose={() => setSelectedNode(null)}
  />
)}
```

---

#### Step 6 — Auto-open config panel after adding a node

In the `addNode` callback, after `setNodes((nds) => [...nds, rfNode])`, add:

```typescript
setSelectedNode(rfNode);
```

So the full `addNode` body ends with:

```typescript
setNodes((nds) => [...nds, rfNode]);
setSelectedNode(rfNode);
```

---

#### Step 7 — Run TypeScript check

After all edits, run from the `frontend/` directory:

```bash
npx tsc -b --noEmit
```

Fix any TypeScript errors before committing. Do not use `@ts-ignore` or `any` casts to suppress errors.

---

#### Step 8 — Commit

Stage only `frontend/src/pages/RetellFlowEditor.tsx` and commit with:

```
fix(voice-flow): fix edge sync between canvas and NodeConfigPanel

- NodeConfigPanel now reads outgoing edges from rfEdges (single source of truth)
  instead of node.data.edges, so canvas-drawn edges are immediately visible in panel
- Edge condition and destination edits in panel update rfEdges via dedicated callbacks
- Removed broken handleNodeChange edge-sync block that deleted canvas-drawn edges
- Auto-open NodeConfigPanel when node added via palette
```

---

### 5. ACCEPTANCE CRITERIA

- **Draw edge on canvas → open source node panel**: the new edge appears in "Outgoing Edges" with empty condition field
- **Edit edge condition in NodeConfigPanel**: the canvas edge label updates in real time (truncated to 40 chars); `flowToRetellNodes` picks it up correctly when publishing
- **Change edge destination in NodeConfigPanel**: the canvas edge re-routes to the selected node
- **Edit node name or instruction in NodeConfigPanel**: canvas-drawn edges are NOT deleted; they survive the update
- **Add Node via palette**: config panel opens immediately for the new node
- **Publish to Retell**: `flowToRetellNodes` correctly serializes all edges (canvas-drawn and panel-edited) into the Retell flow payload with correct `transition_condition.prompt` values
- **`npx tsc -b --noEmit` passes with 0 errors**
- **No regressions**: existing flow load, Global Prompt editing, node dragging, edge deletion (×), and MiniMap all continue to work
- Do NOT introduce `gray-*`, `blue-*`, `green-*`, or `red-*` Tailwind classes anywhere
- Do NOT change any file other than `frontend/src/pages/RetellFlowEditor.tsx`

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now.