Now I have a complete, accurate picture. Let me write the Round 8 spec.

**Summary of actual state:**
- All 4 backend endpoints: ✅ complete
- RetellFlowEditor page: ✅ complete (no `loadError` state though — Round 7 review approved this but it was never actually added)
- Campaigns.tsx voice section: ✅ complete (badge fix `mode !== 'flow'` already applied)
- App.tsx route: ✅ registered
- TypeScript: ✅ passes clean

**Genuinely remaining:**
1. `loadError` state missing from `RetellFlowEditor.tsx` — fetch failure silently shows empty canvas
2. `Toast.tsx` context value is not memoized (`value={{ ... }}` inline object) — causes `useToast()` to return a new reference every time any toast fires, which triggers the `useEffect` in `RetellFlowEditor` (since `toast` is in its deps), resetting the canvas mid-edit

---

```
ROUND 8 ENGINEERING SPEC — Retell Voice Node Editor: Remaining Fixes

═══════════════════════════════════════════════════════════════
1. OBJECTIVE
═══════════════════════════════════════════════════════════════
Fix two genuine bugs: (A) RetellFlowEditor silently shows an empty canvas on load failure instead of an error screen, and (B) the Toast context value is an unstable object reference that triggers the RetellFlowEditor fetch useEffect on every toast notification, resetting unsaved canvas edits.

═══════════════════════════════════════════════════════════════
2. FILES TO CHANGE — EXACTLY THESE THREE, NOTHING ELSE
═══════════════════════════════════════════════════════════════
- frontend/src/pages/RetellFlowEditor.tsx
- frontend/src/components/Toast.tsx

═══════════════════════════════════════════════════════════════
3. DO NOT TOUCH
═══════════════════════════════════════════════════════════════
- backend/app/routers/accounts.py — backend is complete, do not modify
- frontend/src/pages/Campaigns.tsx — fully implemented, do not modify
- frontend/src/App.tsx — route registered, do not modify
- frontend/src/components/Sidebar.tsx — no nav change needed
- Any file not listed in section 2
- Do NOT rewrite, reorganize, or refactor any logic already present
- Do NOT add imports that are already imported
- Do NOT remove any existing functionality

IMPORTANT: Read each target file in full before editing. Make minimal, surgical changes only.

═══════════════════════════════════════════════════════════════
4. IMPLEMENTATION
═══════════════════════════════════════════════════════════════

────────────────────────────────────────────────────────────────
FIX A: loadError state in frontend/src/pages/RetellFlowEditor.tsx
────────────────────────────────────────────────────────────────

CURRENT STATE (lines 451–465):
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api.get(`/accounts/voice/${agentId}/flow`)
      .then(res => {
        const flowData = res.data as RetellFlow;
        setFlow(flowData);
        setGlobalPrompt(flowData.global_prompt);
        setNodes(retellNodesToFlow(flowData.nodes));
        setEdges(retellEdgesToFlow(flowData.nodes));
      })
      .catch(() => toast.error('Failed to load voice flow'))
      .finally(() => setLoading(false));
  }, [agentId, setNodes, setEdges, toast]);

CHANGES REQUIRED:

Step A1 — Add loadError state alongside the existing loading state:
  Replace:
    const [saving, setSaving] = useState(false);
    const [loading, setLoading] = useState(true);
  With:
    const [saving, setSaving] = useState(false);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(false);

Step A2 — Update the useEffect to set loadError on failure AND remove toast from deps:
  Replace the entire useEffect block:
    useEffect(() => {
      api.get(`/accounts/voice/${agentId}/flow`)
        .then(res => {
          const flowData = res.data as RetellFlow;
          setFlow(flowData);
          setGlobalPrompt(flowData.global_prompt);
          setNodes(retellNodesToFlow(flowData.nodes));
          setEdges(retellEdgesToFlow(flowData.nodes));
        })
        .catch(() => toast.error('Failed to load voice flow'))
        .finally(() => setLoading(false));
    }, [agentId, setNodes, setEdges, toast]);
  With:
    useEffect(() => {
      api.get(`/accounts/voice/${agentId}/flow`)
        .then(res => {
          const flowData = res.data as RetellFlow;
          setFlow(flowData);
          setGlobalPrompt(flowData.global_prompt);
          setNodes(retellNodesToFlow(flowData.nodes));
          setEdges(retellEdgesToFlow(flowData.nodes));
        })
        .catch(() => {
          toast.error('Failed to load voice flow');
          setLoadError(true);
        })
        .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [agentId, setNodes, setEdges]);

  NOTE: `toast` is intentionally excluded from deps. It is called only in the catch
  handler where a stale reference is fine. Including it causes the effect to re-run
  whenever any toast notification fires (see Fix B), resetting canvas state mid-edit.

Step A3 — Add error screen guard after the loading guard.
  CURRENT loading guard (around line 544):
    if (loading) {
      return (
        <div className="h-screen bg-slate-950 flex items-center justify-center">
          <div className="text-sky-500 font-black uppercase tracking-widest animate-pulse">Loading Flow...</div>
        </div>
      );
    }

  Add the following block IMMEDIATELY AFTER the loading return, before the main return:
    if (loadError) {
      return (
        <div className="h-screen bg-slate-950 flex flex-col items-center justify-center gap-6">
          <p className="text-rose-400 font-black uppercase tracking-widest text-sm">Failed to load voice flow</p>
          <button
            onClick={() => navigate(`/campaigns/${campaignId}`)}
            className="flex items-center gap-2 text-slate-400 hover:text-slate-100 transition-all text-[10px] font-black uppercase tracking-widest"
          >
            <ArrowLeft size={16} /> Back to Sequence
          </button>
        </div>
      );
    }

  ArrowLeft and navigate are already imported/declared in this file — do not add duplicate imports.

────────────────────────────────────────────────────────────────
FIX B: Memoize Toast context value in frontend/src/components/Toast.tsx
────────────────────────────────────────────────────────────────

ROOT CAUSE: Line 48 creates a new object literal on every render of ToastProvider:
  <ToastContext.Provider value={{ success: (m) => add('success', m), error: (m) => add('error', m) }}>

Whenever any toast fires (add/dismiss changes toasts state), ToastProvider re-renders,
creating a new context value object. Every useToast() consumer sees a new reference and
re-renders. In RetellFlowEditor, this was causing the fetch useEffect to re-run (toast
was in deps), resetting the canvas. Fix B removes toast from deps (step A2 above) and
also fixes the root cause here.

CURRENT STATE (line 1 imports):
  import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'

Step B1 — Add useMemo to the import:
  Replace:
    import { createContext, useCallback, useContext, useEffect, useRef, useState } from 'react'
  With:
    import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from 'react'

Step B2 — Memoize the context value in ToastProvider.
  CURRENT (inside ToastProvider, the return statement's Provider line):
    return (
      <ToastContext.Provider value={{ success: (m) => add('success', m), error: (m) => add('error', m) }}>

  Replace only that Provider opening tag with a memoized value. Insert the useMemo
  declaration immediately before the return statement, then use the variable:

  Before the return, add:
    const value = useMemo(
      () => ({ success: (m: string) => add('success', m), error: (m: string) => add('error', m) }),
      [add]
    );

  Then change the Provider opening tag from:
    <ToastContext.Provider value={{ success: (m) => add('success', m), error: (m) => add('error', m) }}>
  To:
    <ToastContext.Provider value={value}>

  `add` is already a useCallback (stable reference), so `value` will only change if
  `add` changes (effectively never). This makes useToast() return a stable reference.

═══════════════════════════════════════════════════════════════
5. VERIFICATION STEPS (Gemini must perform these)
═══════════════════════════════════════════════════════════════
After making changes:
1. Read the full content of RetellFlowEditor.tsx and verify:
   - `loadError` state exists alongside `loading`
   - `.catch()` calls both `toast.error(...)` and `setLoadError(true)`
   - Error screen renders between the loading guard and the main return
   - `toast` is NOT in the useEffect dependency array
2. Read the full content of Toast.tsx and verify:
   - `useMemo` is in the import list
   - `const value = useMemo(...)` exists before the return statement
   - `<ToastContext.Provider value={value}>` uses the memoized variable, not an inline object
3. Run TypeScript check: cd frontend && npx tsc --noEmit
   - Must produce zero errors
4. Confirm git diff shows changes to ONLY these two files plus possibly bridge log

═══════════════════════════════════════════════════════════════
6. ACCEPTANCE CRITERIA
═══════════════════════════════════════════════════════════════
- [ ] RetellFlowEditor: if /accounts/voice/{agentId}/flow returns an error, user sees a "Failed to load voice flow" screen with a back button, not an empty canvas
- [ ] RetellFlowEditor: showing a toast notification (success or error) does NOT re-fetch the flow or reset the canvas
- [ ] Toast.tsx: ToastContext.Provider receives a memoized value object, not an inline object literal
- [ ] `toast` is absent from RetellFlowEditor's fetch useEffect dependency array
- [ ] npx tsc --noEmit passes with zero errors in frontend/
- [ ] No other files modified
- [ ] All existing RetellFlowEditor functionality intact: drag nodes, edit config panel, publish to Retell, add nodes, delete edges

═══════════════════════════════════════════════════════════════
DESIGN SYSTEM REMINDERS (Gemini always gets these wrong — READ THIS)
═══════════════════════════════════════════════════════════════
- Colors: slate-*, sky-*, emerald-*, rose-*, indigo-* ONLY. No gray-*, blue-*, green-*, red-*
- The error screen uses rose-400 for the error text (not red-400)
- No React.FC — plain function components only
- `api` is imported as `import { api } from '../api/client'` (named export)
- `useToast` is imported as `import { useToast } from '../components/Toast'`
- Do not add wrapper divs with p-6 max-w-5xl mx-auto
```