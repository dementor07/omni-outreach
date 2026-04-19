---
title: Queue Page
category: product
tags: [queue, UI, monitoring, filters, tasks]
sources: []
updated: 2026-04-13
---

# Queue Page

**Route:** `/queue`  
**File:** `frontend/src/pages/Queue.tsx`

Live task-queue inspector. Lets operators see what work is scheduled, locked, sent, or failed — before it becomes visible to outreach recipients.

## Data Sources

| Hook | Endpoint | Data |
|------|----------|------|
| `useQueueStats` | `GET /queue/stats` | Aggregate row counts by `{ channel, status }` |
| `useQueueList` | `GET /queue?campaign_id&status&limit` | Up to 200 task rows |
| `useListCampaigns` | `GET /campaigns` | For the campaign name lookup map |

## Layout Sections

### Hero Banner

Headline: "Watch scheduled outreach before it becomes customer-visible". Shows a "Updated X ago" timestamp badge (using `formatRelative`) when the queue query has run at least once.

### Top Stat Cards (4-column)

| Card | Computed from | Accent |
|------|--------------|--------|
| Queued | `queueStats.filter(status='queued').sum(cnt)` | sky |
| Locked | `queueStats.filter(status='locked').sum(cnt)` | amber |
| Sent | `queueStats.filter(status='sent').sum(cnt)` | emerald |
| Failed | `queueStats.filter(status='failed').sum(cnt)` | rose |

### Filter Bar (3 dropdowns)

- **Campaign** — All campaigns or one specific campaign (fed from `useListCampaigns`)
- **Channel** — All channels or a specific one (derived dynamically from the current task list, not hardcoded)
- **Status** — All / queued / locked / sent / failed / skipped

Channel filter is applied client-side (`tasks.filter(t => !channel || t.channel === channel)`) because it comes from a live fetch rather than a URL param.

### Task Table

Limit: 200 rows fetched server-side.

| Column | Content |
|--------|---------|
| Lead | `first_name + last_name` or `linkedin_url` or "Unknown" |
| Campaign | Campaign name (looked up via `campaignMap`), or truncated UUID if unknown |
| Channel | `Badge asChannel` |
| Status | `Badge asStatus` |
| Scheduled | `formatScheduled(scheduled_at)` — shows "In X" or "X ago" relative time |
| Retries | Retry count; amber + bold when > 0, slate-400 when 0 |

Empty state: "No tasks match this filter" with a helper tip.

## API Call

`GET /queue?campaign_id=…&status=…&limit=200`  
Response: array of task objects with fields: `id`, `lead_id`, `first_name`, `last_name`, `linkedin_url`, `campaign_id`, `channel`, `status`, `scheduled_at`, `retry_count`.

## Related Pages

- [[dashboard]]
- [[dispatcher]]
- [[campaigns]]
