You are an expert React/TypeScript and FastAPI engineer implementing a feature.

**Settings.tsx is already fully implemented.** There's nothing for Gemini to build. Here's what's already in the file:

- **Tab navigation** — `linkedin | email | voice` tabs with `rounded-full` pill style
- **All three GET queries** — `useQuery` on `/accounts/linkedin`, `/accounts/email`, `/accounts/voice`
- **All three POST mutations** — `addLinkedIn`, `addEmail`, `addVoice` wired to the correct endpoints
- **Delete mutation** — `deleteAccount` covering all three types via `DELETE /accounts/{type}/{id}`
- **LinkedIn test connection** — `handleTest` → `POST /accounts/linkedin/{id}/test` with inline pass/fail feedback
- **`AccountModal` component** — single modal that switches forms by active tab; LinkedIn (4 fields), email (7 fields incl. SMTP config + TLS toggle), voice (2 fields)
- **DataTable rendering** — all three tabs use the shared `<DataTable>` component with correct columns and `emptyMessage`
- **Styling** — matches the spec exactly: `rounded-3xl border border-slate-200 bg-white shadow-sm`, sky-500 accents, `inputCls` constant for form fields

**Nothing is missing.** If you're seeing a gap, it's more likely a backend route that isn't wired up yet (FastAPI side) or a router entry missing in `App.tsx`. Want me to check those?

IMPORTANT RULES:
- Only modify the files listed in FILES TO CHANGE
- Do not touch any file listed in DO NOT TOUCH
- Do not refactor, rename, or clean up anything not in scope
- Do not remove existing features
- After implementing, run: git add -A && git commit -m "feat: <short description>"
- If you hit an error, fix it before committing

Begin implementation now.