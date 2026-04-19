---
title: Dashboard
category: product
tags: [dashboard, overview, stats, UI, monitoring]
sources: []
updated: 2026-04-13
---

# Dashboard

**Route:** `/`  
**File:** `frontend/src/pages/Dashboard.tsx`

Mission-control view. All stats are live-polled. Data refreshes every 30 seconds.

## Data Sources

| Hook | Endpoint | What it fetches |
|------|----------|-----------------|
| `useListCampaigns` | `GET /campaigns` | All campaigns (name, status, tz, caps, simulation_mode) |
| `useQueueStats` | `GET /queue/stats` | Row-level breakdown: `{ channel, status, cnt }` |
| `useOverviewStats` | `GET /overview/stats` | Aggregated: `total_leads`, `invited`, `accepted`, `sent` |

`overview/stats` is preferred. If unavailable, the dashboard falls back to computing invited/accepted/sent from `queueStats` manually for backward compatibility.

## Layout Sections

### Hero Banner

Rounded card with headline "Mission control for outreach operations". Shows a "Live data / Refreshes every 30 seconds" pill in the top-right.

### First-Run Onboarding

Visible only when `campaigns.length === 0` and the campaigns query has resolved (not loading). Shows:
- Sky-blue CTA: "Create first campaign" → `/campaigns`
- Secondary link: "Connect LinkedIn account" → `/settings`

### Stat Cards — Row 1 (4-column grid)

| Card | Value source | Accent |
|------|-------------|--------|
| Total Leads | `overview.total_leads` | sky |
| Invites Sent | `overview.invited` | emerald |
| Accepted | `overview.accepted` | amber |
| Messages Sent | `overview.sent` | sky |

### Stat Cards — Row 2 (3-column grid)

| Card | Value | Accent |
|------|-------|--------|
| Active Campaigns | `campaigns.filter(c => c.status !== 'archived').length` | emerald |
| Queued Tasks | sum of `queueStats` rows with `status === 'queued'` | sky |
| Failed Tasks | sum of `queueStats` rows with `status === 'failed'` | rose |

### Bottom Panels (2-column: 1.3fr / 0.7fr)

**Channel Breakdown (left):**  
`DataTable` showing every `{ channel, status, count }` row from queue stats.  
Columns: Channel (Badge `asChannel`), Status (Badge `asStatus`), Count (right-aligned, tabular numbers).

**Campaign Footprint (right):**  
Up to 6 campaigns as clickable cards. Each card links to `/campaigns/:id?tab=leads`.  
Card content: campaign name, timezone, simulation/live badge, daily cap + invite cap.

## Component Dependencies

- `StatCard` — value + icon + accent colour + loading skeleton
- `DataTable` — reusable table with column renderers
- `EmptyState` — zero-state panel with icon + description + optional action
- `Badge` — `asChannel` / `asStatus` variants

## Related Pages

- [[campaigns]]
- [[queue-page]]
- [[channels]]
