You are an expert React/TypeScript and FastAPI engineer implementing a feature.

Now I have everything I need. Here is the Round 2 spec:

---

## ROUND 2 SPEC — Fix Retell Voice Node Editor (2 bugs)

---

### 1. OBJECTIVE

Fix the two bugs that caused Round 1 rejection: (1) FastAPI route ordering that shadows `GET /voice/flows`, and (2) the voice section in `ConfigSidebar` using dark-mode input styles inside a light-mode white panel.

---

### 2. FILES TO CHANGE

```
backend/app/routers/accounts.py
frontend/src/pages/Campaigns.tsx
```

**Do not touch any other file.** `App.tsx`, `RetellFlowEditor.tsx`, all other router files, `SequentialBuilder.tsx`, `sequencer.py`, `dispatcher.py` — leave them exactly as they are.

---

### 3. DO NOT TOUCH

- `frontend/src/App.tsx` — route already correctly wired at line 35
- `frontend/src/pages/RetellFlowEditor.tsx` — already correctly implemented
- `backend/app/routers/accounts.py` — all 4 new endpoints (`GET/PATCH /voice/{agent_id}/prompt`, `GET/PATCH /voice/{agent_id}/flow`) are already correctly implemented; only move one block
- Any other file not listed under FILES TO CHANGE
- Every non-voice section of `ConfigSidebar` in `Campaigns.tsx` (delay, email, linkedin, template, delete button, etc.)
- Everything in `Campaigns.tsx` outside the `ConfigSidebar` function (canvas, node palette, `ActionNode`, `CustomEdge`, campaign form, etc.)

---

### 4. IMPLEMENTATION

#### Fix A — FastAPI route ordering in `backend/app/routers/accounts.py`

**Problem:** `GET /voice/flows` is declared at line 259, after `GET /voice/{agent_id}/flow` (line 196). FastAPI matches routes in registration order. A request to `/accounts/voice/flows` is caught by the `{agent_id}` route with `agent_id="flows"`, which then fails the DB lookup with 404 and never reaches the correct handler.

**Fix:** Move the entire `GET /voice/flows` handler block to appear **immediately after** `POST /voice` (currently at line 109) and **before** `DELETE /voice/{agent_id}` (currently at line 117).

The target order for the `# ── Voice agents ──` section must be:

```
@router.get("/voice")          # list_voice_agents — no params, keep first
@router.post("/voice")         # create_voice_agent — no params
@router.get("/voice/flows")    # list_retell_flows — STATIC, must be before {agent_id} routes
@router.delete("/voice/{agent_id}")
@router.get("/voice/{agent_id}/prompt")
@router.patch("/voice/{agent_id}/prompt")
@router.get("/voice/{agent_id}/flow")
@router.patch("/voice/{agent_id}/flow")
```

Cut the `list_retell_flows` function block (the `@router.get("/voice/flows")` decorator + its entire async function body) from its current position at line ~259 and paste it between `create_voice_agent` and `delete_voice_agent`. Do not alter the function body in any way.

---

#### Fix B — ConfigSidebar voice section styling in `frontend/src/pages/Campaigns.tsx`

**Problem:** The voice standard mode inputs and flow mode button use hardcoded dark-theme Tailwind classes (`bg-slate-800`, `text-slate-100`, `border-slate-700`, `text-slate-300`, `rounded-md`) which are completely wrong inside the white panel (`bg-white border-l border-slate-200`). All other fields in `ConfigSidebar` use the shared constants `inputClassName` and `labelCls` defined at lines 1017–1018.

```ts
// These are defined at the bottom of Campaigns.tsx — use them:
const labelCls = 'mb-2 block text-[10px] font-black uppercase tracking-widest text-slate-400'
const inputClassName = 'w-full rounded-xl border-none bg-slate-50 px-4 py-3 text-sm font-bold text-slate-900 outline-none ring-1 ring-slate-900/5 transition-all focus:bg-white focus:ring-4 focus:ring-sky-100'
```

**Fix:** Inside the `isVoice && mode === 'simple'` block (currently lines ~794–840), replace all hardcoded input/label/button classes as follows:

1. Both `<label>` elements: replace `className="block text-xs font-medium text-slate-300 mb-1"` → `className={labelCls}`

2. The Begin Message `<input>`: replace its entire `className` string with `{inputClassName}`

3. The System Prompt `<textarea>`: replace its `className` string with `` {`${inputClassName} min-h-[200px] resize-none`} ``

4. The "Save Prompt" `<button>`: replace its `className` with:
   ```
   "w-full btn-tactile bg-slate-900 py-3 text-[10px] font-black uppercase tracking-widest text-white hover:bg-slate-800 disabled:opacity-40"
   ```

Inside the `isVoice && mode === 'flow'` block (currently lines ~842–857):

5. The "Open Flow Editor" `<button>`: replace its `className` with:
   ```
   "w-full flex items-center justify-between px-4 py-3 rounded-xl bg-sky-500 text-white text-[10px] font-black uppercase tracking-widest hover:bg-sky-600 transition-all"
   ```
   Keep the `<span>Open Flow Editor</span>` and `<span className="text-sky-100">→</span>` children unchanged.

6. The node/edge count `<p>` (currently `className="text-xs text-slate-500 text-center"`): leave it unchanged — it is already correct.

Do not change any other part of the `ConfigSidebar` function.

---

### 5. ACCEPTANCE CRITERIA

- `GET /accounts/voice/flows` returns 200 with Retell flow list — not a 404 from the agent DB lookup
- Standard mode: selecting a retell-llm agent shows Begin Message input and System Prompt textarea rendered with light background (`bg-slate-50`), dark text, consistent with the rest of the ConfigSidebar
- Flow mode: "Open Flow Editor" button is visible in sky-500 blue, navigates to `/campaigns/:id/voice-flow/:agentId` on click
- Node/edge count displays below the button when flow data is available
- No TypeScript errors (`tsc --noEmit` passes)
- `RetellFlowEditor.tsx` unchanged — still renders the ReactFlow canvas, node panel, and Publish button
- All non-voice parts of `ConfigSidebar` (delay, email account, template textarea, delete button) are completely unchanged
- No other file has been modified

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now.