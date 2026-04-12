## Review: Round 5 — Retell Flow Editor Edge Desync Fix

### 1. Goal Implementation

The round 5 goal was to fix edge desync between canvas and `NodeConfigPanel`, auto-open config on new node, and add delete button. All main objectives are delivered:

- `NodeConfigPanel` reads from `edges` state directly (`edges.filter(e => e.source === node.id)`) — single source of truth ✅
- `handleEdgeUpdate` / `handleEdgeDestinationChange` callbacks implemented ✅  
- `addNode` calls `setSelectedNode(rfNode)` to auto-open panel ✅
- `onPaneClick={() => setSelectedNode(null)}` ✅
- Delete button in panel header with `onDelete` prop ✅
- `instruction.type: 'prompt'` and `transfer_destination.type: 'predefined'` fixed ✅
- `ReactFlowProvider` + `RetellFlowInner` refactor for `useReactFlow` hook scope ✅

### 2. Issues Found

**Residual dead state write in `onConnect` (lines 474–487):**
```ts
setNodes((nds) =>
  nds.map((n) => {
    if (n.id === params.source && n.data.type === 'conversation') {
      return { ...n, data: { ...n.data, edges: [...(n.data.edges ?? []), newRetellEdge] } };
    }
    return n;
  })
);
```
`flowToRetellNodes` (line 88) reconstructs edges from `rfEdges` and ignores `node.data.edges` entirely. So this `setNodes` call writes to state that is never serialized — phantom state. The fix was supposed to *remove* this redundancy, but it wasn't removed from `onConnect`. Not a runtime crash, but it's the original source of the desync bug pattern and will confuse future edits.

### 3. TypeScript Errors

None visible. The `OnNodesChange<Node<RetellNode>>` / `OnEdgesChange<Edge<RetellEdge>>` generics on `RetellFlowInnerProps` (lines 319–320) are correct.

### 4. Nothing Broken

Existing features (publish, load, custom edges, node visuals) are intact.

---

**Verdict: APPROVE**

The primary edge desync fix works correctly — `NodeConfigPanel` now derives outgoing edges from `rfEdges` state, not `node.data.edges`. The residual `setNodes` in `onConnect` writes dead state but causes no functional regression since serialization bypasses it. Flag for cleanup in round 6 spec.