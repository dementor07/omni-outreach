Good — the build is clean with zero TypeScript errors. Now I have everything I need to write an accurate Round 6 spec. Here's what the code review reveals is still genuinely missing:

1. `agentPrompt` not cleared on agent switch → flash of stale data
2. No inline error state when a flow-type agent is selected in Standard mode (backend returns 400, only a toast fires, form stays blank with no explanation)
3. Flow node/edge count doesn't refresh after returning from the editor
4. `ConnectionLineType` imported but unused in `RetellFlowEditor.tsx`

---

```
═══════════════════════════════════════════════════════════════
ROUND 6 — RETELL VOICE NODE EDITOR: POLISH + UX BUG FIXES
═══════════════════════════════════════════════════════════════

────────────────────────────────────────────────────────────
1. OBJECTIVE
────────────────────────────────────────────────────────────
Fix four UX bugs in the already-implemented Retell voice node
editor: stale prompt flash on agent switch, missing inline
error state for agent-type mismatch, stale flow count after
returning from the sub-canvas, and an unused import.

────────────────────────────────────────────────────────────
2. FILES TO CHANGE
────────────────────────────────────────────────────────────
- frontend/src/pages/Campaigns.tsx
- frontend/src/pages/RetellFlowEditor.tsx

That is all. Two files. Do not touch any other file.

────────────────────────────────────────────────────────────
3. DO NOT TOUCH
────────────────────────────────────────────────────────────
- backend/app/routers/accounts.py — all four voice endpoints
  are complete and correct; do not modify them
- frontend/src/App.tsx — route is registered; do not touch
- frontend/src/pages/RetellFlowEditor.tsx — the entire
  ReactFlow canvas, node types, edge types, NodeConfigPanel,
  RetellFlowInner, flowToRetellNodes, retellNodesToFlow,
  retellEdgesToFlow, addNode, handlePublish — none of this
  logic changes. Only the import line changes (see Fix D).
- Any part of Campaigns.tsx that is not the ConfigSidebar
  voice section (lines 774–858). Do not modify the campaign
  canvas, node definitions, edge logic, CustomEdge, Layout,
  ActionNode, routing, queries, or templates section.
- Do NOT change color tokens. Colors are: slate-*, sky-*,
  emerald-*, rose-*, indigo-*. Never use gray-*, blue-*,
  green-*, red-*.
- Do NOT add React.FC. Use plain function components.
- Do NOT switch `import { api }` to `import api`. The client
  exports a named const: `export const api = axios.create(...)`.
  The named import `{ api }` is correct in both files.

────────────────────────────────────────────────────────────
4. IMPLEMENTATION
────────────────────────────────────────────────────────────

── FIX A: Clear stale agentPrompt when agent changes ────────
FILE: frontend/src/pages/Campaigns.tsx
LOCATION: the useEffect that loads agentPrompt (currently
  around line 676–683)

CURRENT CODE:
  useEffect(() => {
    if (mode !== 'standard' || !selectedVoiceAgentId) return;
    setPromptLoading(true);
    api.get(`/accounts/voice/${selectedVoiceAgentId}/prompt`)
      .then(r => setAgentPrompt(r.data))
      .catch(() => toast.error('Failed to load agent prompt'))
      .finally(() => setPromptLoading(false));
  }, [selectedVoiceAgentId, mode, toast]);

CHANGE: At the top of the effect body, before the `if` guard,
add:
  setAgentPrompt(null);
  setPromptSaving(false);

REASON: Without this, switching agents shows the previous
agent's begin_message and general_prompt for the duration of
the network request. The null clears the form immediately and
the existing promptLoading skeleton shows while fetching.

FINAL SHAPE OF EFFECT:
  useEffect(() => {
    setAgentPrompt(null);
    setPromptSaving(false);
    if (mode !== 'standard' || !selectedVoiceAgentId) return;
    setPromptLoading(true);
    api.get(`/accounts/voice/${selectedVoiceAgentId}/prompt`)
      .then(r => setAgentPrompt(r.data))
      .catch(() => toast.error('Failed to load agent prompt'))
      .finally(() => setPromptLoading(false));
  }, [selectedVoiceAgentId, mode, toast]);


── FIX B: Inline error state for agent-type mismatch ────────
FILE: frontend/src/pages/Campaigns.tsx
LOCATION: Same ConfigSidebar component.

ADD one new state variable in ConfigSidebar alongside the
existing state declarations (around line 668):
  const [promptError, setPromptError] = useState<string | null>(null);

UPDATE Fix A's effect to also clear and set this error:
  useEffect(() => {
    setAgentPrompt(null);
    setPromptError(null);
    setPromptSaving(false);
    if (mode !== 'standard' || !selectedVoiceAgentId) return;
    setPromptLoading(true);
    api.get(`/accounts/voice/${selectedVoiceAgentId}/prompt`)
      .then(r => { setAgentPrompt(r.data); setPromptError(null); })
      .catch((err) => {
        const status = err?.response?.status;
        if (status === 400) {
          setPromptError('This agent uses Nested Flow and cannot be edited in Standard mode. Switch to Nested Flow mode above.');
        } else {
          toast.error('Failed to load agent prompt');
        }
      })
      .finally(() => setPromptLoading(false));
  }, [selectedVoiceAgentId, mode, toast]);

UPDATE the JSX block that renders the standard mode form
(currently starting at line 788 with
`{mode === 'standard' && selectedVoiceAgentId && (`).

Inside that block, after the promptLoading skeleton and the
`agentPrompt ? (...)  : null` branch, add a third branch for
promptError. The complete conditional should be:

  {promptLoading ? (
    /* existing skeleton */
  ) : promptError ? (
    <div className="rounded-xl bg-rose-950/40 border border-rose-800/50 p-4">
      <p className="text-[11px] text-rose-300 leading-relaxed">{promptError}</p>
    </div>
  ) : agentPrompt ? (
    /* existing begin_message + general_prompt + save button */
  ) : null}

Do not change anything else in this block.


── FIX C: Refresh flow count after returning from editor ────
FILE: frontend/src/pages/Campaigns.tsx
LOCATION: The useEffect that loads flowMeta (currently around
  line 685–694).

CURRENT CODE:
  useEffect(() => {
    if (mode !== 'flow' || !selectedVoiceAgentId) return;
    api.get(`/accounts/voice/${selectedVoiceAgentId}/flow`)
      .then(r => {
        const nodes = r.data.nodes ?? [];
        const edges = nodes.flatMap((n: any) => [...(n.edges ?? []), ...(n.edge ? [n.edge] : [])]);
        setFlowMeta({ node_count: nodes.length, edge_count: edges.length });
      })
      .catch(() => setFlowMeta(null));
  }, [selectedVoiceAgentId, mode]);

PROBLEM: This only runs when selectedVoiceAgentId or mode
changes. If the user opens the flow editor, publishes changes,
and navigates back, the count displayed is stale (from the
first load). The effect does not re-run because neither dep
changed.

FIX: Import `useLocation` from react-router-dom at the top of
the file (it is likely already imported — check first).
Add `const location = useLocation()` inside ConfigSidebar
(add it near the existing `const { id: campaignId } = useParams()`).
Add `location.key` to the dependency array of the flowMeta
effect so it re-runs every time the user navigates back to
this page:

  useEffect(() => {
    if (mode !== 'flow' || !selectedVoiceAgentId) return;
    api.get(`/accounts/voice/${selectedVoiceAgentId}/flow`)
      .then(r => {
        const flowNodes = r.data.nodes ?? [];
        const flowEdges = flowNodes.flatMap((n: any) => [...(n.edges ?? []), ...(n.edge ? [n.edge] : [])]);
        setFlowMeta({ node_count: flowNodes.length, edge_count: flowEdges.length });
      })
      .catch(() => setFlowMeta(null));
  }, [selectedVoiceAgentId, mode, location.key]);

NOTE: Also rename the inner `nodes` and `edges` variables to
`flowNodes` and `flowEdges` to avoid shadowing the outer
`nodes` prop of ConfigSidebar. This is the only rename
needed; do not change any other variable names.

CHECK: `useLocation` is almost certainly already imported in
Campaigns.tsx alongside `useParams` and `useNavigate`. If it
is not, add it to the existing react-router-dom import line.
Do not create a new import line.


── FIX D: Remove unused import from RetellFlowEditor ────────
FILE: frontend/src/pages/RetellFlowEditor.tsx
LOCATION: Line 26 in the @xyflow/react import block.

CURRENT:
  ConnectionLineType,

This identifier is imported but never referenced anywhere in
the file. Remove it from the import list.

The import block currently contains:
  import {
    ReactFlow,
    ReactFlowProvider,
    Background,
    Controls,
    MiniMap,
    addEdge,
    useNodesState,
    useEdgesState,
    Node,
    Edge,
    Connection,
    NodeTypes,
    Handle,
    Position,
    Panel,
    BaseEdge,
    EdgeLabelRenderer,
    getBezierPath,
    useReactFlow,
    MarkerType,
    ConnectionLineType,   ← REMOVE THIS LINE
    type EdgeProps,
    type OnNodesChange,
    type OnEdgesChange,
  } from '@xyflow/react';

After removal, the rest of RetellFlowEditor.tsx is unchanged.

────────────────────────────────────────────────────────────
5. ACCEPTANCE CRITERIA
────────────────────────────────────────────────────────────
- [ ] Selecting a new voice agent in Standard mode immediately
      clears the previous agent's begin_message and
      general_prompt fields; the skeleton loader shows while
      the new prompt fetches.
- [ ] Selecting a conversation-flow agent (e.g. "Omni Demo v2")
      in Standard mode shows the rose-tinted inline error
      message: "This agent uses Nested Flow and cannot be
      edited in Standard mode. Switch to Nested Flow mode
      above." No toast fires for this case.
- [ ] Selecting a retell-llm agent in Standard mode still
      shows begin_message + general_prompt inputs and Save
      Prompt button as before. Save still works.
- [ ] After publishing changes in RetellFlowEditor and clicking
      "Back to Sequence", the node/edge count in the
      ConfigSidebar flow section reflects the current number
      of nodes/edges (re-fetches on navigation).
- [ ] The inner variables in the flowMeta effect are named
      `flowNodes` and `flowEdges`, not `nodes` and `edges`.
- [ ] `ConnectionLineType` does not appear anywhere in
      RetellFlowEditor.tsx.
- [ ] `npx tsc --noEmit` produces zero errors.
- [ ] The ReactFlow canvas in RetellFlowEditor, all three node
      types, the NodeConfigPanel, edge deletion, node deletion,
      add-node palette, and Publish to Retell button all
      continue to work exactly as before.
- [ ] No other parts of Campaigns.tsx (canvas, edges,
      non-voice sidebar sections) are changed.
```