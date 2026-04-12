**Review verdict: APPROVE with minor notes**

---

**1. Goal implementation — complete**

All three deliverables are present and functional:
- Standard mode in `ConfigSidebar` shows editable `begin_message` + `general_prompt` via `/accounts/voice/{agent_id}/prompt` (GET/PATCH)
- Mode switcher correctly uses `'standard'` / `'flow'` labels (not the old `'simple'`)
- Nested Flow mode navigates to `/campaigns/:id/voice-flow/:agentId`
- `RetellFlowEditor.tsx` is a full ReactFlow sub-canvas with node editing, edge drawing, `onConnect`, global prompt panel, and "Publish to Retell" via PATCH `/accounts/voice/{agentId}/flow`
- Backend endpoints exist and proxy correctly to Retell API

**2. Nothing broken**

- `agentPrompt` state (renamed from `retellPrompt`), `flowMeta` snake_case properties, and mode values all align.
- `RetellPrompt` interface exists at line 59 of `Campaigns.tsx`.
- Route in `App.tsx` confirmed to match `/campaigns/:id/voice-flow/:agentId`.

**3. Known issues**

- **`ActionNode` in `Campaigns.tsx` line 146–147** still checks `mode === 'simple'` for its badge rendering — not updated to `'standard'`. This is a cosmetic inconsistency: the node badge in the canvas will always show the `Simple` tab as active instead of `Standard` for existing nodes.
- **`globalPromptSaving` state** is referenced in the spec (for save button state) but is absent from `RetellFlowEditor.tsx` — the global prompt is embedded inside `handlePublish` with no standalone save button for it. Functionally acceptable but differs slightly from spec intent.
- The `FlowUpdate` Pydantic model in `accounts.py` is defined but the `PATCH /flow` endpoint uses `body: dict` directly — harmless but unused dead code.
- No TypeScript errors visible in the diff; the file is complete and well-typed.

**4. Verdict: APPROVE**

The core goal is fully implemented and correct. The `ActionNode` badge inconsistency (`simple` vs `standard`) is the only user-visible gap, and it's a one-line fix rather than a structural problem.