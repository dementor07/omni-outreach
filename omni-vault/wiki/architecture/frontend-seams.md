---
title: Frontend Seams & Cleanup Backlog
category: architecture
tags: [frontend, tech-debt, cleanup, uniformity]
updated: 2026-06-08
---

# Frontend Seams & Cleanup Backlog

Concrete non-uniformities found in the 2026-06-08 full frontend read. These are what make new work re-discover patterns instead of inheriting them. Ordered by leverage. Related: [[frontend-map]], [[canvas-contract]].

## 1. Dead legacy hooks (pure deletion)

6 of 10 `api/client`-based hooks have **no importer** — safe to delete:
`useAnalytics, useBlacklist, useInbox, useOverview, useQueue, useTemplateLibrary`.
(Verified by import sweep + [[codebase-memory-mcp]] graph.) Deleting these removes the bulk of the legacy API surface in one shot.

## 2. API split-brain (one axios, two endpoint families)

It's NOT two transports — `api/client.ts` is the single axios instance. The split is **endpoint families**: v2 event-sourced (`/projections/*`, `/canvas/*`, `/ai/*`) via `api/v2.ts` vs legacy REST (`/leads` campaign-scoped, `/blacklist`, `/queue`) via raw `api.get` hooks. After deleting the 6 dead hooks, only 4 legacy consumers remain to migrate: `useCampaigns`→Campaigns/index, `useLeads`→CsvImport, `useNotifications`→NotificationCenter, `useSequenceSteps`→SequentialBuilder. Then `api/v2.ts` is the one world. New work should ALWAYS use `api/v2.ts` (the `useLeads.ts` vs `projections.leads` confusion in the 2026-06 leads-view fix came from this exact split).

## 3. Duplicate utilities

`lib/format.ts` and `lib/time.ts` both define `timeAgo` AND `formatScheduled` with different implementations. Pick one home (suggest `lib/time.ts` for dates, `lib/format.ts` for names/query), re-export or delete the dupes.

## 4. DataTable not used uniformly

A generic `DataTable<T>` exists (`columns[{key,header,render}]` + `rows`), but `Leads.tsx` and `Contacts.tsx` hand-roll `<table>`. Either converge list pages onto `DataTable` or accept the hand-roll as the pattern — but be consistent. (The new dynamic-column Leads view is a good candidate to migrate once `DataTable` gains per-cell `kind` rendering.)

## 5. Badge status gaps

`Badge.statusVariant` lacks `completed` and `waiting` (lead statuses introduced 2026-06-08) → they render neutral. Add: completed→neutral/success, waiting→warning.

## 6. Canvas contract leaks

Five manifest→frontend leaks (icon, array fields, connection UX, output_fields, runs observability) — fully documented in [[canvas-contract]]. These are the highest-value uniformity work for future integrations.

## 7. Legacy components

`SequentialBuilder.tsx` (495 LOC) + `useSequenceSteps` + `StepIcon` are the pre-canvas linear builder. The canvas (`CampaignEditor`) is the graph successor. Decide: keep SequentialBuilder for simple linear sequences, or retire it. `pages/_legacy/Inbox.legacy.tsx` and `pages/Dashboard.tsx` are legacy-client holdouts.
