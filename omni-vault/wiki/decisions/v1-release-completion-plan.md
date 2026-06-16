---
title: v1 Release Completion Plan — MUST + SHOULD Execution
category: decisions
tags: [v1-release, completion, execution-plan, ship-ready]
sources: [ship-ready-completion-ledger, current-code-verification]
updated: 2026-06-16
---

# v1 Release Completion Plan

**Mandate (2026-06-16):** completeness + feature integration + perfection across the
board for the first complete version release. Scope decided: **MUST + SHOULD** from
[[ship-ready-completion-ledger]]. Execution: build the whole cut, then one review.

## Architectural decisions made this turn
- **Scheduling (B6) → Flink timer.** Use the existing orchestrator's timer service to fire
  schedule transitions, not a DB-polled worker or external cron. Correct for the
  event-sourced spine; the orchestrator already owns keyed timers for delay/wait_until.
- **Scope = MUST + SHOULD.** MUST: W1–W5 wiring, T1 DNC-at-send, T2 analytics endpoint,
  B2 reply classification, B3 inbox reply, B1 AI draft-review, B4 activity log, B7
  conversion alert. SHOULD: T3 email open/click tracking, B5 template library, B6
  scheduling. DEFER to v1.1: P1–P7, Latka.

## Verified-current state (2026-06-16, not trusting the 06-11 ledger)
- W1 CsvImport: still NOT mounted in router. OPEN.
- W3 undo/redo: logic + toolbar buttons exist; NO keydown listener. OPEN.
- W5 notifications: NO backend endpoint/table in v2. OPEN (build, not wire).
- T2 analytics: NO router exposes pipeline/flink metrics. OPEN.
- B4 activity log: NO omni_activity_log table, NO log_activity(). OPEN (build).
- T1 DNC: filter_company only on naukri/enrichment path (transition_worker ~929). OPEN at send.
- B1 approvals: resolve = approve/reject only, no draft field/PATCH. OPEN.

## CORRECTION (2026-06-16 verification) — the ledger over-counted breakage
A live-vs-dead audit (frontend API calls cross-checked against registered routers +
probed against the live box) found:
- **The running app has ZERO broken endpoints.** Every endpoint the *mounted* pages call
  (`projections.*`, `inbox.*`, `ai.*`, `canvas.*`, `nodes`, `integrations`, `approvals`)
  returns 200 live. `/sources/naukri/preview` 405s GET correctly (POST-only).
- **9+ "missing backends" are dead legacy hooks**, imported by NO mounted page:
  `useOverview`, `useQueue`, `useBlacklist`, `useTemplateLibrary`, `useSequenceSteps`,
  `useLeads` (only CsvImport, itself unmounted), + `Dashboard.tsx`. They call `/overview/*`,
  `/queue/*`, `/notifications`, `/leads`, `/template-library` — all 404, but nothing live
  hits them. These are landmines + signal-pollution → **DELETE, don't build backends for.**
- So W5 "notifications backend" etc. are NOT live breakage; the notification bell in the
  live Topbar must be re-checked separately (it may use a different path or be absent).

**Revised v1 surface = (a) delete the dead legacy frontend, (b) build the genuine
ledger features still open: T1, T2, B1, B2, B3, B4, B7, T3, B5, B6.**

## Dependency-ordered phases
1. **Phase 1 — CLASS A wiring** (W1, W3, W2 clickable leads, W4 pagination): pure frontend glue.
2. **Phase 2 — read endpoints** (T2 analytics router, W5 notifications backend+table): backend + UI surface.
3. **Phase 3 — compliance + observability** (T1 DNC-at-send, B4 activity log + instrumentation, B7 conversion alert).
4. **Phase 4 — the AI/inbox core** (B2 reply classifier, B3 inbox reply compose, B1 AI draft-review).
5. **Phase 5 — SHOULD** (T3 email tracking, B5 template library, B6 Flink-timer scheduling).
6. **Phase 6 — regression + visual sweep + ship + verify live.**

Each item lands as its own green commit (ruff + tsc + eslint + audit suite). New backend
behavior gets a regression test in audit/tests/. New tables get an alembic migration.
