---
title: Architectural Mandate — Frontend De-Slopping
category: architecture
tags: [refactor, frontend, technical-debt, standards]
updated: 2026-05-05
---

# Architectural Mandate: Frontend De-Slopping

The frontend implementation has devolved into "Feature Slop," characterized by monolithic components and redundant logic. This document mandates a structural overhaul.

## 1. The "Campaigns.tsx" Mega-Component
- **The Problem**: At 2,000+ lines, `Campaigns.tsx` is an unmaintainable "God Object." It handles navigation, state, canvas rendering, sequential logic, lead tables, settings, and analytics.
- **The Mandate**: Shred `Campaigns.tsx` into a modular directory structure:
  - `src/pages/Campaigns/`
    - `CampaignList.tsx` (The grid view)
    - `CampaignEditor.tsx` (The container)
    - `components/Canvas/` (ReactFlow logic)
    - `components/Sequential/` (Linear view)
    - `components/Panels/` (Settings, Sources, Analytics)
- **Goal**: No single file should exceed 300 lines. Use **Atomic Design** principles.

## 2. Redundancy: The Sequential/Canvas Split
- **The Problem**: `SequentialBuilder.tsx` is a needless addition that duplicates 80% of the logic found in the Canvas.
- **The Mandate**: Converge on a **Single Source of Truth**. The "Sequential" view should be a **layout mode** of the Canvas data, not a separate codebase. 
- **Refactor**: Build a `SequentialLayoutEngine` that renders the graph as a list. Delete the standalone `SequentialBuilder`.

## 3. "Prop-Drilling" vs Centralized State
- **The Problem**: State is currently "drilled" through dozens of layers, leading to brittle UI updates.
- **The Mandate**: Use **Zustand** or **React Query** more aggressively to manage shared campaign state. 
- **Goal**: The Sidebar should "know" which node is selected by listening to a store, not by receiving 15 props from the parent.

## 4. Visual Validation
- **The Problem**: Node "Readiness" is a hardcoded guess (check if ID exists).
- **The Mandate**: Implement a **JSON Schema Validator** for every node. A node is only "Ready" if its data payload passes a strict structural check.


### Status Update (2026-05-05) - Phase 4 Mitigation
- **Shredded the Mega-Component**: `Campaigns.tsx` has been refactored into a modular architecture under `src/pages/Campaigns/`.
- **Atomic Design**: Logic is now isolated into `Nodes`, `Edges`, `Sidebar`, and `Panels`.
- **Single Source of Truth**: Unified types and constants now drive both the Canvas and Sequential views.

### Status Update (2026-05-14) — Phase 4 Regression Caught
- A Rules-of-Hooks violation slipped through the shred and bricked the Queue and Sequence tabs on the Campaigns detail page. Operator-discovered, not test-discovered.
- Fixed in commit `f5b7b09`. Full breakdown: [[postmortem-queue-sequence-crash-may-2026]].
- **New mandate clause**: every shred-phase PR must end with a manual "click every tab on every affected route" pass before merge. Compile-clean ≠ render-clean.
- **Tooling gap**: the codebase has no client-side error boundary or Sentry hook, so this took 8 days to surface. See postmortem follow-ups.

### Status Update (2026-05-14, later) — Postmortem follow-ups partially closed
- **Render-throw safety net**: top-level `<ErrorBoundary>` shipped in commit `93673e7` (`frontend/src/components/ErrorBoundary.tsx`). Future shred phases that smuggle in a runtime crash will surface as an in-app fallback panel instead of a blank screen.
- **Lint enforcement**: ESLint flat-config with `eslint-plugin-react-hooks` now installed; `npm run lint:hooks` is the errors-only gate, currently 0 errors. The original Phase 4 violation has been verified to fail this gate.
- **Still open from the mandate**: the "operator clicks every tab on the affected pages" checklist is documented but not yet enforced by tooling — until E2E coverage exists, it relies on the reviewer.
- **Still open from the postmortem**: remote error aggregation (Sentry / GlitchTip), and the backend invariant that no task should reach the UI with a null `campaign_id` (tracked under [[vulnerability-queue-black-box]]).

### Status Update (2026-05-14, later x2) — Pre-stage for dashboard redesign branch
- `VITE_API_BASE` env-var pre-stage shipped in commit `4b9b6e2` so the in-flight Claude Design dashboard work can rebase onto a clean axios contract without baking the wrong base URL into source.
- Same-origin (`/api`) remains the production default. Override only via `.env.local` (gitignored).
- **Hard constraint codified**: never point `VITE_API_BASE` at `omnioutreach.space`. That domain is alias-only in nginx and returns NXDOMAIN. The only live HTTPS endpoint is `srv1575227.hstgr.cloud`. Comment in `client.ts` and `.env.example` both call this out so the next agent doesn't repeat the mistake.
- **No preview/mock mode**: dashboard either talks to the real backend or surfaces a real error state. Decision recorded; do not reverse without explicit user sign-off.

### Status Update (2026-05-14, later x3) — Design-tool PR #1 applied
- Commit `526bc25` lands the dashboard-redesign series' first PR (handoff doc: `pr-handoff/01-env-base.md` in the design bundle at `Downloads/omni-outreach.zip`).
- Two improvements over the in-house `4b9b6e2` pre-stage: `apiBase` is now exported (not module-local) and trailing-slash-stripped, and `useNotifications.ts` derives its SSE URL from `apiBase` instead of hardcoding `/api`. The latter was a real bug: `EventSource` bypasses axios's `baseURL`, so any non-default `VITE_API_BASE` would have broken real-time notifications.
- Subsequent PRs from the same handoff series (full sidebar redesign, hero overhaul, NotificationCenter component, theme toggle, redesigned Approvals/Blacklist/Analytics/Activity/Login screens) are exploratory in the bundle but not yet PR-packaged. Each must land as its own commit with anti-slop + rules-of-hooks self-check, per the handoff convention.
- Verification gate passed: `npm run lint:hooks` 0 errors, `npm run lint` baseline-stable (52 warnings), `npm run build` clean.

### Status Update (2026-05-14, later x4) — Overview screen ported
- Commit `1c45157`: first substantive screen port from the standalone design bundle (`Downloads/omni-design-preview/`). Overview/Dashboard ships with four new shared primitives (`Card` + `CardHeader`, `Button`, `PageHeader`, extended `StatCard`, `Badge.dot`) that every subsequent screen will reuse.
- Decision: hand-port each screen one commit at a time, no big-bang rewrite. The bundle is the visual reference; real router shapes (verified per [[postmortem-queue-sequence-crash-may-2026]] follow-up) are the data contract.
- Decision: no preview/mock mode. Dashboard queries either hit the real backend or surface per-panel error/empty states. Confirmed and codified earlier today.
- Verification: `npm run build` clean, `npm run lint:hooks` 0 errors. Visual verification gated on the in-flight VPS deploy completing (CI was red for 2 days, fixed in `5163370` and `feab4df`).

### Status Update (2026-05-15) — Premium UI migration build unblocked

The four premium-UI commits between `3a37f8c` and `213c868` (UI parity / Style Guide / SequentialBuilder refresh / LeadSources + JobSearch + Analytics + Activity restyle) introduced primitive call sites ahead of the primitives themselves. 39 TS errors blocked the build for ~12 hours. Fixed in commit `6823068` by extending — never breaking — the primitive surface:
- `Badge.size`, `Button.isLoading`, `ChannelIcon.size: number`, `Select.disabled`, `Tabs` accepts `tabs`/`activeTab` aliases.
- One missing import (`Badge` in `Activity.tsx`).

Lesson recorded under [[anti-slop-protocol]]: design-tool drops can introduce call-site assumptions ahead of the primitives. Build the primitives in the same commit, or land an extension PR before the call sites. Don't ship to master with a broken `tsc -b`.

Also: the consolidated dashboard aggregator (`ae60f26`) closes the "five loading states for one page" fragmentation. Single TanStack Query, atomic snapshot, fewer waterfalls. Original per-resource endpoints remain available for other consumers.
