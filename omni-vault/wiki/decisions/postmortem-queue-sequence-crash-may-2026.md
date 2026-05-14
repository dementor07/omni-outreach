---
title: Postmortem — Queue/Sequence Tab Crash After Phase 4 Refactor
category: postmortem
tags: [postmortem, frontend, react-rules-of-hooks, regression, anti-slop]
date: 2026-05-14
commit-fix: f5b7b09
related: [[mandate-frontend-refactor]], [[anti-slop-protocol]], [[vulnerability-queue-black-box]]
---

# Postmortem: Queue / Sequence Tab Crash (2026-05-14)

## Summary

After Phase 4 of [[mandate-frontend-refactor]] (commit `8351051` — "The Big Shred"), the `Campaigns` detail view crashed the moment an operator clicked the **Queue** tab, and intermittently bricked the **Sequence** tab as a downstream effect. The global `/queue` page also threw on any task with a null `campaign_id`. Surfaced by operator testing (antigravity diagnosis pass) on 2026-05-14. Fixed in commit `f5b7b09`.

## Impact

- **Severity**: high — two of the five Campaigns-detail tabs unrenderable; the global Queue page blank-screened for any tenant with unassigned tasks.
- **Window**: 2026-05-06 (Phase 4 deploy) → 2026-05-14 (fix). ~8 days.
- **Detection**: operator self-test, not telemetry. We have no client-side error reporting that would have caught a render-throw; see Follow-ups.

## Root Cause

### Bug 1 — Hook called inside conditional JSX

`frontend/src/pages/Campaigns/index.tsx:334` (post-shred):

```tsx
{activeTab === 'queue' && (
  <DataTable
    ...
    rows={useQueueList({ campaignId: id!, limit: 50 }).data || []}
  />
)}
```

`useQueueList` is a React hook. It only ran when `activeTab === 'queue'`, so the hook count for `<Campaigns />` changed between renders. React's Rules of Hooks invariant fired: **"Rendered fewer hooks than during the previous render"**, which unmounts the entire component subtree.

Sequence tab "sometimes" crashed because once the Campaigns subtree threw and tore down mid-render, navigating to Sequence after Queue inherited a half-unmounted React state — depending on cache hydration timing, that either recovered or re-threw.

This is the canonical Rules-of-Hooks violation. The shred preserved it from a pre-existing inline pattern in the old monolith, then made it visible because the new tab structure made Queue the default-clickable tab for many operators.

### Bug 2 — `null.slice()` in global Queue page

`frontend/src/pages/Queue.tsx:164`:

```tsx
render: (row) => (
  <span className="text-slate-600">
    {campaignMap[row.campaign_id] ?? <span ...>{row.campaign_id.slice(0, 8)}</span>}
  </span>
)
```

When backend returned a task with `campaign_id = null` (orphan task, manual enqueue, or pre-campaign-attach state), the fallback expression evaluated `null.slice(0, 8)` → `TypeError: Cannot read properties of null (reading 'slice')`. Throws inside a column renderer kill the whole table render.

## Fix

[Commit `f5b7b09`](commit-fix:f5b7b09):

1. **Hoisted** `useQueueList` to the top of the `Campaigns` component:
   ```tsx
   const queueListQuery = useQueueList({ campaignId: id, limit: 50 })
   ```
   Now runs on every render regardless of `activeTab`. Costs one extra fetch when the operator isn't on the Queue tab, but `useQueueList` already has `staleTime: 15s` so the wasted bandwidth is bounded.

2. **Null-guarded** the campaign cell in `Queue.tsx` — render an em-dash placeholder for unassigned tasks instead of throwing.

## Why This Slipped Through

- **No visual verification after the refactor.** The Phase 4 commit `8351051` claimed "modular architecture" but no one clicked through the five tabs after it shipped. TypeScript + Vite both built clean — the hook violation is a runtime invariant, not a compile-time one.
- **No client error reporting.** A `componentDidCatch` boundary or Sentry-style hook would have surfaced "Rendered fewer hooks…" within minutes of the first user click. We have neither.
- **Pre-existing pattern carried forward.** The hook-in-JSX call almost certainly existed in the pre-shred monolith too, just less obviously buggy because the monolith had so much top-level state that React's hook-count diff happened to stay stable across renders. The shred made each tab a discrete conditional branch, exposing the latent violation.

## Anti-Slop Protocol Violations

This bug class is exactly what [[anti-slop-protocol]] is supposed to prevent:

| Protocol Rule | Violation |
| --- | --- |
| #5 *"Errors are First-Class Citizens"* | Frontend has no global error boundary. A render-throw blanks the page with no operator-visible reason. |
| #4 *"UI/UX 'Ready' means 'Human-Verified'"* | Phase 4 was marked complete based on the refactor compiling, not on the routes rendering. |
| #2 *"No Mega-Component Expansion"* | Indirectly: the shred itself was correct, but moving without a route re-verification pass turned a single review surface into five. |

## Follow-ups

- [x] **Add a top-level React `<ErrorBoundary>` around the route tree** with a "Something broke — copy debug info" UI and a console-side dump. — shipped 2026-05-14 in commit `93673e7` as `frontend/src/components/ErrorBoundary.tsx`, mounted inside `RequireAuth` so it wraps the authenticated `<Outlet />`. Resets on `useLocation()` pathname change; "Retry this view" button bumps an internal reset key for in-place recovery; "Copy debug info" emits a JSON payload with route, timestamp, UA, error message + truncated stack + component stack.
- [x] **Add a lint rule: `eslint-plugin-react-hooks`'s `rules-of-hooks` is supposed to catch this** — shipped 2026-05-14 in commit `93673e7`. ESLint flat-config (`frontend/eslint.config.js`) with `react-hooks/rules-of-hooks: error` and `react-hooks/exhaustive-deps: warn`. Two npm scripts: `npm run lint` (full pass) and `npm run lint:hooks` (errors-only gate). Verified end-to-end by re-injecting the original `useQueueList` line in `Campaigns/index.tsx:335` — ESLint reported *"React Hook 'useQueueList' is called conditionally."* before revert.
- [ ] Wire Sentry (or self-host GlitchTip) for the frontend; route-level breadcrumbs. **Deferred** — needs a hosting / data-residency / cost decision; the ErrorBoundary covers the "user sees the failure" half today, but we still have no remote aggregation. Open as a standalone follow-up.
- [x] Audit remaining pages for hooks called inside conditional JSX. **Closed by the lint gate**: `npm run lint:hooks` reports 0 errors across `src/`, so no other latent violations exist as of `93673e7`. The manual `grep -nE "use[A-Z][A-Za-z]+\\("` step stays in the runbook in case the rule ever gets disabled.
- [ ] Post-refactor checklist in [[mandate-frontend-refactor]]: every shred phase must end with "operator clicks every tab on the affected pages." — note added to that mandate on 2026-05-14.
- [ ] Tie [[vulnerability-queue-black-box]] follow-ups: tasks with null `campaign_id` shouldn't reach the UI in the first place — investigate where they originate (manual enqueue? deleted-campaign orphans?). **Still open** — the UI is now defended against the symptom, but the backend invariant remains unchecked.
