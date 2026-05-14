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
