---
title: System Gaps Sprint — 20-Cycle Self-Evolving Build
category: decisions
tags: [sprint, gaps, notifications, analytics, canvas, ui, automation]
sources: [full-codebase-audit, competitor-analysis]
updated: 2026-04-19
---

# System Gaps Sprint — 20-Cycle Self-Evolving Build

## Context

Full codebase audit on 2026-04-19 identified **140+ gaps** across 10 categories compared to competitors (Apollo, Instantly, Lemlist, Smartlead, Woodpecker). The system has a solid foundation (25 canvas node types, multi-source lead gen, sequence engine, telemetry overlay) but is missing critical infrastructure and UI features required for a production-ready outreach platform.

## Decision

Execute a 20-cycle brainstorm→implement loop, each cycle producing deployed working code. Prioritize by impact: infrastructure first, then user-facing features, then polish.

## Cycle Plan

### Infrastructure (Cycles 1-5)
1. **Notification System** — `notifications` table, backend event emitter, SSE push, frontend bell + drawer
2. **Activity Log + Real-Time Events** — `activity_log` table, SSE endpoint, live toast notifications for replies/failures
3. **Lead Detail Drawer** — Full profile, message timeline, tags, enrichment data, actions (stop/re-queue/tag)
4. **Lead Table Search/Filter/Pagination** — Text search, status filter, tag filter, date range, proper pagination controls
5. **CSV Import with Field Mapping** — File upload, column preview, drag-and-drop field mapping, duplicate detection, import progress

### Canvas & Flows (Cycles 6-10)
6. **Blacklist / Do-Not-Contact System** — `blacklists` table, check before every dispatch, management UI, import/export
7. **Email Open/Click Tracking** — Tracking pixel endpoint, link redirect endpoint, `email_tracking` table, wire to event nodes
8. **Campaign Analytics Endpoint + UI** — Time-series stats, funnel metrics, per-node performance, export
9. **Template Library** — Global templates page, shared across campaigns, performance ranking, variable autocomplete
10. **Canvas Undo/Redo + Edge Labels** — useUndoRedo hook, Ctrl+Z/Y, visible edge labels on condition branches

### Features (Cycles 11-15)
11. **Webhook + SMS Dispatcher Handlers** — Wire `action_webhook` to HTTP POST, `action_sms` to Twilio or stub
12. **Goal/Conversion Node** — `goal_conversion` node type, marks lead as converted, stops sequence, fires notification
13. **Reply Classification** — AI-powered reply intent detection (interested/not-interested/OOO/auto-reply), route conditionally
14. **Campaign Scheduling** — Start/end dates, scheduled activation/deactivation, timezone-aware cron
15. **Unified Inbox** — Conversations page aggregating all reply threads across channels with reply capability

### Polish (Cycles 16-20)
16. **Bulk Lead Actions** — Multi-select, bulk stop/tag/re-assign/export on lead tables
17. **Dashboard Analytics Charts** — Recharts integration, time-series line charts, funnel bar charts, sparklines in stat cards
18. **Wait-for-Time Node** — Schedule actions at specific times/days, timezone support, business hours enforcement
19. **Campaign Cloning** — Duplicate campaign with full sequence graph, templates, and configuration
20. **Dark Mode + Visual Polish** — Theme toggle, CSS custom properties, consistent dark palette, micro-interactions

## Success Criteria

- Each cycle produces committed, deployed, tested code
- Vault log updated after each cycle
- canvas-editor.md and relevant wiki pages updated for new nodes
- 0 regressions on existing test_dashboard.py (20/20 must stay green)
