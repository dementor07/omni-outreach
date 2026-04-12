You are an expert React/TypeScript and FastAPI engineer implementing a feature.

Now I have everything I need. Here is the round 2 spec:

---

## 1. OBJECTIVE

Harden and finalize `frontend/src/pages/Settings.tsx` — the component is already scaffolded but has one correctness bug (modal form state does not reset on close) and must filter soft-deleted accounts from all three tables on the client side, since the backend `SELECT` queries return rows with `is_active = FALSE`.

---

## 2. FILES TO CHANGE

```
frontend/src/pages/Settings.tsx   ← ONLY FILE YOU MAY TOUCH
```

---

## 3. DO NOT TOUCH

- `frontend/src/components/DataTable.tsx`
- `frontend/src/components/Modal.tsx`
- `frontend/src/components/Badge.tsx`
- `frontend/src/components/Toast.tsx`
- `frontend/src/api/client.ts`
- `frontend/src/lib/time.ts`
- `backend/` — any file at all
- `nginx/` — any file at all
- `frontend/src/App.tsx`
- Any file not listed under "FILES TO CHANGE"

**Gemini warning:** Do NOT add new helper files, hooks, or utilities. Do NOT restructure the component. Do NOT rename anything. Do NOT add features beyond what is specified below. The existing Settings.tsx is largely correct — make the two targeted fixes described in section 4 and nothing else.

---

## 4. IMPLEMENTATION

### 4.1 — Read the current file first

Read `frontend/src/pages/Settings.tsx` in full before making any edits. The component already contains:

- `SettingsTab` union type (`'linkedin' | 'email' | 'voice'`)
- `LinkedInAccount`, `EmailAccount`, `VoiceAgent` types
- `useQuery` calls for all three endpoints
- `addLinkedIn`, `addEmail`, `addVoice`, `deleteAccount` mutations
- `handleTest()` for LinkedIn connection testing
- Tab switcher UI with sky-500 active pill
- `DataTable` usage for all three tabs
- `AccountModal` sub-component with three conditional form bodies
- `inputCls` constant for shared input styling

**Do not rewrite or restructure any of this.**

---

### 4.2 — Fix 1: Filter inactive accounts from all three tables

The backend `GET /accounts/linkedin`, `GET /accounts/email`, and `GET /accounts/voice` all return rows regardless of `is_active`. Apply a client-side filter in the `rows` prop of each `DataTable`.

Locate these three `DataTable` usages and change only the `rows` prop:

**LinkedIn DataTable** — change:
```tsx
rows={linkedinQuery.data || []}
```
to:
```tsx
rows={(linkedinQuery.data || []).filter((a) => a.is_active)}
```

**Email DataTable** — change:
```tsx
rows={emailQuery.data || []}
```
to:
```tsx
rows={(emailQuery.data || []).filter((a) => a.is_active)}
```

**Voice DataTable** — change:
```tsx
rows={voiceQuery.data || []}
```
to:
```tsx
rows={(voiceQuery.data || []).filter((a) => a.is_active)}
```

No other changes to the DataTable call sites.

---

### 4.3 — Fix 2: Reset modal form state on close

**Problem:** The `AccountModal` component holds its own `useState` for `linkedin`, `email`, and `voice` form fields. When the modal is closed and reopened, the previous values persist because the state is never reset.

**Fix:** In the `AccountModal` function component, add a `useEffect` that resets all three form states to their initial values whenever `open` changes from `true` to `false` (i.e., when the modal closes), and also whenever `tab` changes.

Add this import at the top of `AccountModal` (already imported at the file level — `useEffect` is already in the import from `'react'` on line 1, confirmed by `import { FormEvent, useState } from 'react'` — update that import to include `useEffect`):

Change line 1:
```tsx
import { FormEvent, useState } from 'react'
```
to:
```tsx
import { FormEvent, useEffect, useState } from 'react'
```

Then inside `AccountModal`, after the three `useState` declarations, add:

```tsx
useEffect(() => {
  if (!open) {
    setLinkedin({ unipile_id: '', name: '', email: '', daily_invite_cap: 20 })
    setEmail({ from_name: '', from_email: '', smtp_host: '', smtp_port: 587, smtp_username: '', smtp_password: '', smtp_use_tls: true })
    setVoice({ retell_agent_id: '', name: '' })
  }
}, [open])
```

The initial values must exactly match the existing `useState` initializers already in the component.

---

## 5. ACCEPTANCE CRITERIA

- `frontend/src/pages/Settings.tsx` is the only modified file; `git diff --name-only` shows exactly one file.
- `cd frontend && npx tsc --noEmit` exits 0 with no type errors.
- LinkedIn, email, and voice DataTable `rows` props each have `.filter((a) => a.is_active)` applied before the fallback `|| []`.
- Clicking "Remove" on any row triggers the DELETE mutation; the row disappears from the table immediately on the next query invalidation (because it is now filtered out).
- Reopening the "Add" modal after a successful submission shows empty fields, not the previously submitted values.
- Switching tabs while the modal is open and then reopening it shows empty fields.
- All existing features are preserved: LinkedIn "Test" button, per-tab tab switcher, `toast.success`/`toast.error` on mutation outcomes, `Badge` status indicator, `formatDate` on email `created_at`, `handleTest` result inline display.
- No new files created. No imports added beyond the `useEffect` addition to the existing `react` import on line 1.

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now.