Here is the Round 4 spec:

---

## ROUND 4 SPEC — RetellFlowEditor: Custom Edges + Add Node Palette

---

### 1. OBJECTIVE

Add custom deletable edges with visible labels and an "Add Node" bottom palette to `RetellFlowEditor.tsx` — the only file that needs changes this round; everything else is already complete.

---

### 2. FILES TO CHANGE

**Only one file:**

```
frontend/src/pages/RetellFlowEditor.tsx
```

**Current state of this file** (read it before touching anything):
- Lines 1–21: imports from `@xyflow/react` — currently missing `BaseEdge`, `EdgeLabelRenderer`, `getBezierPath`, `useReactFlow`, `MarkerType`, `ConnectionLineType`, `EdgeProps`
- Lines 94–98: `nodeTypes` const — correct, do not change
- Lines 105–111: state declarations — correct, do not change
- Lines 259–298: `<ReactFlow>` JSX — currently uses no `edgeTypes`, no `defaultEdgeOptions`
- Lines 127–138: `fetchFlow` edge mapping — currently sets `type: 'default'` on each edge; needs to change to `type: 'custom'`
- No `CustomEdge` component exists in this file yet
- No "Add Node" palette exists in this file yet

---

### 3. DO NOT TOUCH

- `frontend/src/pages/Campaigns.tsx` — fully implemented, do not read or modify
- `backend/app/routers/accounts.py` — fully implemented, do not read or modify
- `frontend/src/App.tsx` — route already registered, do not modify
- The node components `ConversationNodeCard`, `TransferCallNodeCard`, `EndNodeCard` at lines 49–98 — do not modify
- The `nodeTypes` const at line 94 — do not modify
- The `fetchFlow` function logic — only change `type: 'default'` → `type: 'custom'` in the rfEdges mapping (line 135). Change nothing else in that function.
- The `handlePublish` function — do not modify
- The `handleSaveGlobalPrompt` function — do not modify
- The node config panel (`<aside>`) at lines 301–381 — do not modify
- The header bar at lines 237–255 — do not modify
- The Global Prompt `<Panel>` at lines 280–297 — do not modify

---

### 4. IMPLEMENTATION

#### Step 1 — Expand imports

Add these to the existing `@xyflow/react` import block (lines 3–17). Do not remove any existing import. Add only what is missing:

```ts
BaseEdge,
EdgeLabelRenderer,
getBezierPath,
useReactFlow,
MarkerType,
ConnectionLineType,
type EdgeProps,
```

Also add `nanoid` — check if it's available in the project first by running `grep -r "nanoid" frontend/src`. If found, import it. If not found, use `crypto.randomUUID()` instead (no new dependency).

#### Step 2 — Add `CustomEdge` component

Insert this component **after the `EndNodeCard` component (after line 92) and before the `nodeTypes` const (before line 94)**. Copy this pattern exactly from `Campaigns.tsx` — adapt it for dark theme:

```tsx
function CustomEdge({ id, sourceX, sourceY, targetX, targetY, sourcePosition, targetPosition, selected, label }: EdgeProps) {
  const { deleteElements } = useReactFlow();
  const [edgePath, labelX, labelY] = getBezierPath({ sourceX, sourceY, sourcePosition, targetX, targetY, targetPosition });
  return (
    <>
      <BaseEdge id={id} path={edgePath} style={{ stroke: selected ? '#38bdf8' : '#475569', strokeWidth: selected ? 2 : 1.5 }} />
      <EdgeLabelRenderer>
        <div
          style={{
            position: 'absolute',
            transform: `translate(-50%, -50%) translate(${labelX}px,${labelY}px)`,
            pointerEvents: 'all',
          }}
          className="nodrag nopan"
        >
          {label && (
            <span className="bg-slate-800 border border-slate-700 text-[9px] text-slate-400 px-1.5 py-0.5 rounded-md max-w-[120px] truncate block">
              {label as string}
            </span>
          )}
          {selected && (
            <button
              onClick={(e) => { e.stopPropagation(); deleteElements({ edges: [{ id }] }); }}
              className="mt-0.5 h-4 w-4 flex items-center justify-center rounded-full border border-slate-600 bg-slate-900 text-[10px] font-bold text-slate-400 hover:text-rose-400 hover:border-rose-500 transition mx-auto"
            >
              ×
            </button>
          )}
        </div>
      </EdgeLabelRenderer>
    </>
  );
}
```

#### Step 3 — Add `edgeTypes` and `defaultEdgeOptions`

Insert immediately after the `nodeTypes` const (after line 98, before the `export default function RetellFlowEditor()`):

```ts
const retellEdgeTypes = { custom: CustomEdge };

const retellDefaultEdgeOptions = {
  type: 'custom',
  markerEnd: { type: MarkerType.ArrowClosed, color: '#475569', width: 18, height: 18 },
};
```

Do NOT name these `edgeTypes` or `defaultEdgeOptions` — those names may conflict if this file is ever co-located with Campaigns.tsx. Use the prefixed names above.

#### Step 4 — Fix edge type in `fetchFlow`

In the `fetchFlow` function, find this line (currently line ~135):

```ts
type: 'default',
```

Change it to:

```ts
type: 'custom',
```

That is the only change to `fetchFlow`.

#### Step 5 — Wire `edgeTypes` and `defaultEdgeOptions` into `<ReactFlow>`

Find the `<ReactFlow` JSX opening tag (currently around line 259). Add these two props:

```tsx
edgeTypes={retellEdgeTypes}
defaultEdgeOptions={retellDefaultEdgeOptions}
```

Do not remove or reorder any existing props on `<ReactFlow>`. Just add these two.

#### Step 6 — Add `addNode` function

Inside `RetellFlowEditor()`, after the `updateSelectedNode` function (after line 233), add:

```ts
const addNode = useCallback((type: RetellNode['type']) => {
  const id = `node-${Date.now()}`;
  const newRetellNode: RetellNode = {
    id,
    type,
    name: type === 'conversation' ? 'New Conversation' : type === 'transfer_call' ? 'Transfer Call' : 'End Call',
    display_position: { x: 200 + Math.random() * 200, y: 200 + Math.random() * 200 },
    instruction: { type: 'prompt', text: '' },
    ...(type === 'conversation' ? { edges: [] } : {}),
    ...(type === 'transfer_call' ? { transfer_destination: { type: 'predefined', number: '' } } : {}),
  };
  const rfNode: Node = {
    id,
    type,
    position: newRetellNode.display_position,
    data: { ...newRetellNode },
  };
  setNodes((nds) => [...nds, rfNode]);
}, [setNodes]);
```

#### Step 7 — Add "Add Node" palette panel

Inside the `<ReactFlow>` component, after the existing `<Panel position="top-right">` block (after line 297, before `</ReactFlow>`), add a second panel:

```tsx
<Panel position="bottom-center">
  <div className="flex items-center gap-2 bg-slate-900/95 border border-slate-700 rounded-xl px-3 py-2 shadow-2xl backdrop-blur">
    <span className="text-[9px] font-black uppercase tracking-widest text-slate-500 mr-1">Add Node</span>
    <button
      onClick={() => addNode('conversation')}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-slate-800 border border-slate-700 hover:border-slate-500 text-slate-300 text-[10px] font-bold transition-all"
    >
      <span className="w-2 h-2 rounded-full bg-slate-500 inline-block" />
      Conversation
    </button>
    <button
      onClick={() => addNode('transfer_call')}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-indigo-950 border border-indigo-800 hover:border-indigo-600 text-indigo-300 text-[10px] font-bold transition-all"
    >
      <span className="w-2 h-2 rounded-full bg-indigo-500 inline-block" />
      Transfer
    </button>
    <button
      onClick={() => addNode('end')}
      className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-rose-950 border border-rose-900 hover:border-rose-700 text-rose-300 text-[10px] font-bold transition-all"
    >
      <span className="w-2 h-2 rounded-full bg-rose-500 inline-block" />
      End Call
    </button>
  </div>
</Panel>
```

#### Step 8 — TypeScript verification

After all edits, run:

```bash
cd C:\Users\navij\Downloads\omni-outreach\frontend && npx tsc --noEmit
```

Fix any TypeScript errors before finishing. Do not suppress with `// @ts-ignore` or `as any` casts. If `EdgeProps` does not include `label` in the version installed, check `@xyflow/react` version first with `cat frontend/package.json | grep xyflow`, then look up the correct prop name — it may be `data.label` or accessed via the edge object.

---

### 5. ACCEPTANCE CRITERIA

- `CustomEdge` renders a truncated label badge mid-edge showing `transition_condition.prompt` (up to 40 chars) for edges that have a label
- Clicking an edge selects it; a `×` delete button appears under the label badge; clicking it removes the edge from the canvas
- Selected edges highlight in `sky-300` (`#38bdf8`), unselected in `slate-600` (`#475569`)
- Edges have arrowhead markers at the target end
- The bottom-center panel shows three "Add Node" buttons: Conversation (slate), Transfer (indigo), End Call (rose)
- Clicking any "Add Node" button adds a new node to the canvas at a random position within the visible area
- Newly added nodes can be clicked to open the right-side config panel
- Newly added nodes are included in the "Publish to Retell" payload (they are in the `nodes` ReactFlow state)
- `npx tsc --noEmit` exits 0 with no errors
- No existing functionality is broken: node click → config panel still works, Global Prompt save still works, Publish to Retell still works, Back navigation still works