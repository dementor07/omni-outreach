---
title: Engineering Standard — The Anti-Slop Protocol
category: architecture
tags: [standards, code-quality, agent-mandate]
updated: 2026-05-05
---

# Engineering Standard: The Anti-Slop Protocol

This document establishes the "Zero Slop" rule for all future development. Any agent (Claude, Copilot, Gemini) contributing to this codebase must adhere to these standards.

## 1. No "Dead Code" Implementation
- Features like the `activity_log` or `tracking` must be fully integrated (instrumented) before they are considered "Done."
- If a table exists, the system must write to it. If a router exists, the UI must use it.

## 2. No "Mega-Component" Expansion
- Do not add more lines to `Campaigns.tsx`. 
- New UI features must be built as **isolated functional components** in their own files.

## 3. High-Signal Variables
- Variables in templates (`{{first_name}}`) must be **validated at the Editor level**.
- Do not allow a user to save a sequence that uses variables not present in the campaign's lead data.

## 4. UI/UX "Ready" means "Human-Verified"
- A node is NOT "Ready" just because it has an ID.
- "Ready" status requires a **Payload Check**: Are all required fields (Subject, Body, Time, etc.) non-empty and correctly formatted?

## 5. Errors are First-Class Citizens
- Backend errors (exceptions) must be caught and stored in the `queue.error` column.
- The UI must **always** show the human-readable reason for a failure in the Queue and Lead tabs.


## Status Update (2026-05-14) — Frontend rule #5 enforcement

Two pieces of enforcement infrastructure for rule #5 ("Errors are First-Class Citizens") landed on the frontend in commit `93673e7`:

1. **Top-level `<ErrorBoundary>`** wraps the authenticated route `<Outlet />` in `App.tsx`. Render-throws no longer blank the page — operators see a recoverable panel with a "Retry this view" button and a "Copy debug info" affordance that emits a structured JSON payload (route, timestamp, UA, error message + truncated stacks). Source: `frontend/src/components/ErrorBoundary.tsx`.
2. **ESLint with `eslint-plugin-react-hooks`** is now installed and runs `rules-of-hooks: error`. The exact bug class from [[postmortem-queue-sequence-crash-may-2026]] (hook called inside conditional JSX) is caught at lint time. Two scripts: `npm run lint` and `npm run lint:hooks`. Both run from `frontend/`. Current state: 0 errors, 52 warnings (exhaustive-deps + unused-vars hygiene).

These do not satisfy rule #5 in full — there is still no remote error aggregation (Sentry / GlitchTip is the next decision) — but they close the worst gap: the *operator-invisible blank screen*.


## Status Update (2026-05-14, later) — Two days of red CI ignored

Rule #5 violation in the wild: between 2026-05-12 and 2026-05-14, every CI run on `master` was failing on `ruff check backend/` (22 errors, including three `F821` undefined-name bugs that would NameError at runtime). The pipeline is `lint → test → build → deploy`, so the deploy webhook never fired. The visual dashboard redesign that had been merged into `master` sat there for two days without ever reaching the production VPS.

Two of the F821s were real, customer-facing bugs:
- `routers/queue.py`: `POST /queue/{id}/retry` and `POST /queue/bulk-retry` would have `NameError`'d on first call (missing `execute` import).
- `services/job_search.py`: any job-search run hitting a `"10K+"`-style employee string would `NameError` mid-pipeline (missing `re` import).

The symptom that surfaced this — *"the site doesn't look any different after the redesign"* — turned out to be a deploy-pipeline outage, not a UI bug. We had the signal (red CI), and we ignored it for two days because nobody was looking at the CI tab.

**Mitigations** (commit `5163370` and ops):
1. Imports added; ruff auto-fixed the rest. CI green again.
2. **Operational follow-up needed**: every PR or push must be preceded by a CI-status check. If CI has been red for >1 commit, fix CI before pushing more changes — otherwise you're piling commits on a broken pipeline and don't know which one is to blame.

This pattern (lint-time bug catches that someone has to actually look at) is exactly what rule #5 is supposed to prevent. The ESLint `rules-of-hooks` gate on the frontend is the parallel mechanism for that side. Both only work if the result is read.
