Here is the Round 7 spec:

---

## ROUND 7 — RETELL VOICE NODE EDITOR: FINAL POLISH & BUG FIXES

---

### 1. OBJECTIVE

Fix two remaining bugs in the Retell voice node feature: (1) the ActionNode mode badge never highlights "Simple" after a user explicitly sets Standard mode in the ConfigSidebar, and (2) the RetellFlowEditor shows a blank canvas with no feedback when the flow API call fails.

---

### 2. FILES TO CHANGE

- `frontend/src/pages/Campaigns.tsx` — one-line fix in `ActionNode`
- `frontend/src/pages/RetellFlowEditor.tsx` — add error state when flow fails to load

---

### 3. DO NOT TOUCH

**Do not touch any of the following — they are fully working and must not be modified:**

- `backend/app/routers/accounts.py` — all four voice endpoints are complete and correct
- `frontend/src/App.tsx` — route `/campaigns/:id/voice-flow/:agentId` is already registered
- `frontend/src/api/client.ts` — do not change this file or any import of it
- The `ConfigSidebar` function in `Campaigns.tsx` — the voice section (Standard mode prompt editor, Flow mode "Open Flow Editor" button, flowMeta node/edge count) is complete. Do not rewrite or move any of this logic.
- The `RetellFlowEditor` page logic — `retellNodesToFlow`, `retellEdgesToFlow`, `flowToRetellNodes`, `ConversationNode`, `TransferCallNode`, `EndNode`, `CustomEdge`, `NodeConfigPanel`, `RetellFlowInner`, `handlePublish`, `onConnect`, `addNode`, `handleNodeChange`, `handleEdgeUpdate`, `handleEdgeDestinationChange` — all correct, do not change.
- The `nodeTypes`, `retellEdgeTypes`, `retellDefaultEdgeOptions` constants in `RetellFlowEditor.tsx`.
- Non-voice sections of `Campaigns.tsx`: email, LinkedIn, delay nodes, canvas pan/zoom, lead table, campaign settings, import modal, etc.
- `SequentialBuilder.tsx`, `sequencer.py`, `dispatcher.py`
- `frontend/src/components/Sidebar.tsx`

---

### 4. IMPLEMENTATION

#### Fix A — ActionNode badge: `mode === 'simple'` → `mode !== 'flow'`

**File:** `frontend/src/pages/Campaigns.tsx`  
**Location:** `ActionNode` function, approximately line 146.

Current code:
```tsx
const mode = (data as any).mode || 'simple'
// ...
<div className={`px-2 py-0.5 text-[8px] font-black uppercase tracking-widest rounded-md transition-all ${mode === 'simple' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-400'}`}>Simple</div>
<div className={`px-2 py-0.5 text-[8px] font-black uppercase tracking-widest rounded-md transition-all ${mode === 'flow' ? 'bg-slate-900 text-white shadow-sm' : 'text-slate-400'}`}>Flow</div>
```

**Root cause:** `ConfigSidebar` calls `onUpdate({ mode: 'standard' })` when the user clicks the "Standard" button (line ~736). The node data then has `mode: 'standard'`. But `ActionNode` checks `mode === 'simple'` — which is never true after the user explicitly selects Standard in the sidebar. Result: neither pill is highlighted.

**Fix:** Change the condition for the "Simple" pill from `mode === 'simple'` to `mode !== 'flow'`. The `mode || 'simple'` default on the line above is fine as-is — do not change it.

After fix:
```tsx
<div className={`px-2 py-0.5 text-[8px] font-black uppercase tracking-widest rounded-md transition-all ${mode !== 'flow' ? 'bg-white text-slate-900 shadow-sm' : 'text-slate-400'}`}>Simple</div>
```

This is a **single token change on one line**. Do not change any other line in `ActionNode`.

---

#### Fix B — RetellFlowEditor: show error state when flow fails to load

**File:** `frontend/src/pages/RetellFlowEditor.tsx`

**Root cause:** The current `useEffect` (line ~450) calls `.catch(() => toast.error('Failed to load voice flow'))` then `.finally(() => setLoading(false))`. After a failure, `loading` is `false` but `flow` is `null` and `nodes`/`edges` are empty arrays. The component renders the full ReactFlow canvas with no nodes and no error — the user sees a blank dark canvas with no explanation.

**Fix:** Add a `loadError` boolean state. Set it to `true` in the catch handler. Render an error screen when `!loading && loadError`.

Step-by-step:

1. Add state at the top of `RetellFlowEditor` (alongside the existing `loading` state):
   ```tsx
   const [loadError, setLoadError] = useState(false);
   ```

2. In the existing `useEffect` that calls `api.get(...)`, update the `.catch` to also set `loadError`:
   ```tsx
   .catch(() => {
     toast.error('Failed to load voice flow');
     setLoadError(true);
   })
   ```
   Do not change `.finally(() => setLoading(false))` — leave it as-is.

3. Add an error screen render block immediately after the existing loading block (after the `if (loading) { return ... }` block):
   ```tsx
   if (loadError) {
     return (
       <div className="h-screen bg-slate-950 flex flex-col items-center justify-center gap-4">
         <p className="text-rose-400 font-black uppercase tracking-widest text-sm">Failed to load flow</p>
         <p className="text-slate-500 text-xs">This agent may not be a conversation-flow type, or the Retell API is unreachable.</p>
         <button
           onClick={() => navigate(`/campaigns/${campaignId}`)}
           className="flex items-center gap-2 text-slate-400 hover:text-slate-100 transition text-[10px] font-black uppercase tracking-widest mt-4"
         >
           <ArrowLeft size={16} /> Back to Sequence
         </button>
       </div>
     );
   }
   ```

   Colors: `rose-400` for the error text, `slate-500` for the description, `slate-400`/`slate-100` for the back button. No `red-*`, `gray-*`, or `green-*`.

4. Do not change any other part of the component. The existing loading screen, the `RetellFlowProvider`/`RetellFlowInner` render, the header, or the `handlePublish` function are all correct.

---

### 5. ACCEPTANCE CRITERIA

- **Badge fix**: Select a voice node on the canvas → open ConfigSidebar → the "Standard" button is highlighted. The `ActionNode` card immediately shows the "Simple" pill with `bg-white text-slate-900 shadow-sm` (lit state). Switching to "Nested Flow" highlights the "Flow" pill and dims "Simple". Switching back to "Standard" re-highlights "Simple". For new nodes (no mode field set), "Simple" is still highlighted by default.
- **Badge fix**: For all non-voice nodes (email, delay, LinkedIn, etc.), the "Simple" badge remains highlighted as before — no regression.
- **Error state**: Navigate to `/campaigns/:id/voice-flow/invalid-agent-id` (or any agent ID that returns a 400/502 from the flow endpoint) → page shows rose-400 "Failed to load flow" message with a back button instead of a blank canvas. The toast.error also fires as before.
- **No regressions**: The RetellFlowEditor still loads and renders correctly for valid conversation-flow agents. All node types render, clicking opens NodeConfigPanel, "Publish to Retell" still calls PATCH correctly.
- **No TypeScript errors**: `npx tsc --noEmit` returns zero errors.
- **No changes to backend**: `accounts.py` is not modified.
- **No changes to App.tsx, Sidebar.tsx, api/client.ts**, or any non-voice feature.