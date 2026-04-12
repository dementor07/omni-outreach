You are an expert React/TypeScript and FastAPI engineer implementing a feature.

Here is the Round 6 spec:

---

## Round 6 — Bug-Fix Pass

Five targeted fixes. No new features.

### What was found (and why each matters)

**Fix A — TypeScript build error** (`RetellFlowEditor.tsx`)
`useMemo` (React) and `ConnectionLineType` (@xyflow/react) are imported but never referenced. With `noUnusedLocals` these are hard TS errors. Remove them from their respective import lines.

**Fix B — Dead code in `onConnect`** (`RetellFlowEditor.tsx`)
Round 5 made `rfEdges` the single source of truth for outgoing edges. But `onConnect` still writes the new edge back into `n.data.edges` via a `setNodes` call. `flowToRetellNodes` and `NodeConfigPanel` both ignore `n.data.edges`, so this call is pure dead code. Remove it and drop `setNodes` from the dependency array.

**Fix C — Forbidden fields in Retell PATCH body (frontend)** (`RetellFlowEditor.tsx`)
`handlePublish` spreads the entire `flow` object (`...flow`) which includes `conversation_flow_id`. Retell's `update-conversation-flow` endpoint treats that as a read-only field and returns 422. Replace the spread with an explicit payload: `{ global_prompt, nodes, start_node_id }` only.

**Fix D — Same bug, defensive layer (backend)** (`accounts.py`)
`update_voice_agent_flow` forwards the raw request `body` dict to Retell with no filtering. Even after Fix C, the backend should be the authoritative allow-list. Extract only `global_prompt`, `nodes`, `start_node_id` before the Retell PATCH call.

**Fix E — Stale prompt shown when switching agents** (`Campaigns.tsx`)
When switching from agent A to agent B in standard mode, the old prompt data stays in the inputs until the new API call resolves. Add `setAgentPrompt(null)` as the first line of the load effect, and remove `toast` from the dependency array (it's stable but triggers false exhaustive-deps warnings).

---

Spec written to `.bridge_logs/round_06_gemini_task_spec.md`. Pass that file to Gemini CLI for implementation.

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now.