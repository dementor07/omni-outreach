All five fixes are correctly implemented. Here's the review:

---

**Fix A (unused `useMemo`):** Correctly removed from both `RetellFlowEditor.tsx` and `Campaigns.tsx`. `ConnectionLineType` in `Campaigns.tsx` is used, so it was correctly left alone.

**Fix B (dead code in `onConnect`):** The `setNodes` block that was mirroring edge data into `n.data.edges` is cleanly removed. Dependency array updated from `[setEdges, setNodes]` to `[setEdges]`. Correct — ReactFlow manages edges independently; storing them in node data was redundant and error-prone.

**Fix C (forbidden fields in PATCH body):** Changed from `...flow` spread (which would include read-only fields) to explicit `{ global_prompt, nodes, start_node_id: flow.start_node_id }`. The `if (!flow) return` guard at line 478 means `flow.start_node_id` is safe.

**Fix D (backend allow-list):** Dictionary comprehension filters to only `["global_prompt", "nodes", "start_node_id"]` before forwarding to Retell API. Correct and defensive.

**Fix E (stale prompt on agent switch):** `setAgentPrompt(null)` is already at line 679 (from prior round), and `toast` was correctly removed from the `useEffect` dependency array — `toast` from `react-hot-toast` is stable but was causing unnecessary re-triggers.

**No issues found.** All changes are surgical and correct.

**VERDICT: APPROVE**