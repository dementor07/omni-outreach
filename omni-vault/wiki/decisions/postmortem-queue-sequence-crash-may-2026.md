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

- [ ] Add a top-level React `<ErrorBoundary>` around the route tree with a "Something broke — copy debug info" UI and a console-side dump.
- [ ] Wire Sentry (or self-host GlitchTip) for the frontend; route-level breadcrumbs.
- [ ] Audit remaining pages for hooks called inside conditional JSX: `grep -nE "use[A-Z][A-Za-z]+\\(" frontend/src/pages/**/*.tsx | grep -v "^.*const .*= use"` — anything that *isn't* an assignment is suspect.
- [ ] Add a lint rule: `eslint-plugin-react-hooks`'s `rules-of-hooks` is supposed to catch this — verify it's installed AND that `index.tsx:334` would have been flagged (it should be).
- [ ] Post-refactor checklist in [[mandate-frontend-refactor]]: every shred phase must end with "operator clicks every tab on the affected pages."
- [ ] Tie [[vulnerability-queue-black-box]] follow-ups: tasks with null `campaign_id` shouldn't reach the UI in the first place — investigate where they originate (manual enqueue? deleted-campaign orphans?).
