---
title: Campaigns
category: product
tags: [configuration, limits, accounts, UI, tabs, settings-form, stats]
sources: []
updated: 2026-04-13
---

# Campaigns

A campaign is the master container for a target audience and an outreach sequence.

## Configuration Fields

Stored in the `campaigns` table. Editable in the **Settings tab** of the campaign detail view.

| Field | Type | Purpose |
|-------|------|---------|
| `name` | text | Campaign display name |
| `timezone` | text | Timezone string for scheduling (e.g. `Asia/Kolkata`) |
| `daily_lead_cap` | integer | Max new leads processed per day |
| `invite_daily_cap` | integer | Max LinkedIn invites sent per day (safety limit) |
| `active_hours_start` | 0–23 | Beginning of daily outreach window |
| `active_hours_end` | 0–23 | End of daily outreach window |
| `screening_prompt` | text | AI prompt used by the screener service to pre-qualify leads |
| `simulation_mode` | boolean | If true, dispatcher marks tasks as sent but does **not** call external APIs |
| `sequence_mode` | `canvas` \| `sequential` | Controls which sequence builder UI renders |

## Campaign List View (`/campaigns`)

- Lists all campaigns in card or table form
- "New Campaign" button opens `CampaignForm` modal
- Each campaign row links to the campaign detail view
- `CampaignForm` modal: name, timezone, daily_lead_cap, invite_daily_cap — `POST /campaigns`

## Campaign Detail View (`/campaigns/:id`)

Four-tab layout. The active tab is preserved in the URL as `?tab=…`.

### Detail Header

- Campaign name (h2)
- Timezone slug (muted)
- **Simulation badge** — amber "Simulation" badge shown when `simulation_mode === true`
- **Stats mini-bar** (hidden on small screens, `hidden lg:flex`):
  - `total` / `invited` / `accepted` / `stopped` — pulled from `GET /campaigns/{id}/stats` via `useCampaignStats`

### Leads Tab (`?tab=leads`)

`DataTable` scoped to this campaign. Columns:

| Column | Content |
|--------|---------|
| Lead | Name (bold) + company (muted) |
| Status | `Badge asStatus` |
| Invited | `invited_at` date |
| Accepted | `accepted_at` date |
| Replied | `replied_at` date |

### Queue Tab (`?tab=queue`)

Same task table as [[queue-page]] but pre-filtered to this campaign. Columns: Lead, Channel, Status, Scheduled, Retries.

### Sequence Tab (`?tab=sequence`)

Renders either the [[canvas-editor]] (when `campaign.sequence_mode === 'canvas'`) or the [[sequential-builder]] (when `sequence_mode === 'sequential'`).

### Settings Tab (`?tab=settings`)

**CampaignSettings form** — all 8 editable fields in a 2-column grid:

```
[Name]              [Timezone]
[Daily Lead Cap]    [Daily Invite Cap]
[Active Hours Start][Active Hours End]
[Screening Prompt — full-width textarea]
[Simulation Mode toggle]
```

Save button: `PATCH /campaigns/{id}` with the updated field values.

## Account Assignment

Campaigns must have sending identities assigned to them:
- **LinkedIn Accounts**: Assigned via `campaign_linkedin_accounts` join table. The [[dispatcher]] load-balances invites across all active accounts assigned to the campaign.
- **Email & Voice**: Assigned directly at the node level in the [[canvas-editor]] (stored in `sequence_nodes.data`).

## Lead Generation

Campaigns can automatically generate leads via Apify and Serper using the `job_search_configs` linked to the campaign. See [[job-search-ui]] and [[job-search-pipeline]].

## Related Pages

- [[canvas-editor]]
- [[sequential-builder]]
- [[leads-page]]
- [[queue-page]]
- [[job-search-ui]]
- [[dispatcher]]
