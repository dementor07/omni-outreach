---
title: Campaigns
category: product
tags: [configuration, limits, accounts, UI, tabs, settings-form, stats, lead-gen]
sources: []
updated: 2026-04-21
---

# Campaigns

A campaign is the master container for a target audience, its lead-intake configuration, and the sequence that decides what happens next.

## Configuration FieldsStored in the `campaigns` table. Editable in the **Settings** tab of the campaign detail view.

| Field | Type | Purpose |
|-------|------|---------|
| `name` | text | Campaign display name |
| `timezone` | text | Timezone string for scheduling (for example `Asia/Kolkata`) |
| `daily_lead_cap` | integer | **Configured but not enforced as of 2026-04-28.** The column is persisted; nothing in `lead_gen.upsert_lead`, `dispatcher`, or the worker reads it. Treated as advisory until a real cap-enforcement path is wired in. |
| `invite_daily_cap` | integer | Per-LinkedIn-account daily invite ceiling enforced by `dispatcher._handle_linkedin_invite`. Note: the *campaign* field is unused; the dispatcher reads `linkedin_accounts.daily_invite_cap` per account, not this column. |
| `active_hours_start` | 0–23 | Beginning of the daily outreach window. Enforced in `dispatcher._in_active_hours`. |
| `active_hours_end` | 0–23 | End of the daily outreach window. Enforced in `dispatcher._in_active_hours`. |
| `screening_prompt` | text | Default AI screening criteria used by the screener service |
| `simulation_mode` | boolean | If true, the [[dispatcher]] marks tasks as sent without calling external APIs |
| `sequence_mode` | `canvas` \| `sequential` | Controls whether the campaign uses the nodal canvas or the linear builder |

> **Audit note (2026-04-28):** `daily_lead_cap` and the campaign-level `invite_daily_cap` are configured by operators in the UI but the only cap actually enforced at runtime is `linkedin_accounts.daily_invite_cap` (per-account). Both campaign-scoped caps are dead fields.


## Campaign List View (`/campaigns`)

- Lists campaigns in a compact management view.
- "New Campaign" opens `CampaignForm` and posts to `POST /campaigns`.
- Selecting a row/card navigates into the campaign detail workspace.

## Campaign Detail View (`/campaigns/:id`)

Five-tab layout. The active tab is preserved in the URL as `?tab=...`.

### Detail Header

- Campaign name and timezone.
- Amber **Simulation** badge when `simulation_mode === true`.
- Desktop stats mini-bar from `GET /campaigns/{id}/stats`: `total`, `invited`, `accepted`, `stopped`.

### Leads Tab (`?tab=leads`)

Campaign-scoped [[leads-page]] table. Core columns: Lead, Status, Invited, Accepted, Replied.

### Sources Tab (`?tab=sources`)

`CampaignSourcesPanel` bridges campaign management with [[lead-sources-ui]]:

- Lists the campaign's `lead_gen_configs` from `GET /lead-gen/configs/{campaign_id}`.
- Shows label/display name, provider availability, schedule badge, and last-run metadata.
- "Run now" buttons trigger `POST /lead-gen/trigger` per config.
- Polls `GET /lead-gen/runs?campaign_id=...&limit=10` every 15 seconds for recent run state, counts, and `triggered_by`.
- Includes a direct link to the full [[lead-sources-ui]] page.

### Queue Tab (`?tab=queue`)

Same task table as [[queue-page]] but pre-filtered to this campaign. Columns: Lead, Channel, Status, Scheduled, Retries.

### Sequence Tab (`?tab=sequence`)

Renders either the [[canvas-editor]] (when `campaign.sequence_mode === 'canvas'`) or the [[sequential-builder]] (when `sequence_mode === 'sequential'`).

Recent lead-gen/canvas integration points now surface here too:

- The `trigger_start` card shows a lead-source count badge and scheduled-source count.
- In Live mode, the trigger card shows source injection counts from the last 60 seconds.

### Settings Tab (`?tab=settings`)

**CampaignSettings form** — all campaign-level controls in a compact grid:

```
[Name]              [Timezone]
[Daily Lead Cap]    [Daily Invite Cap]
[Active Hours Start][Active Hours End]
[Screening Prompt — full-width textarea]
[Simulation Mode toggle]
```

Save action: `PATCH /campaigns/{id}`.

## Account Assignment

Campaigns need sending identities or provider credentials behind the nodes they use:

- **LinkedIn accounts**: assigned via `campaign_linkedin_accounts`; the [[dispatcher]] load-balances invite work across active accounts.
- **Email and Voice**: assigned per node inside the [[canvas-editor]].
- **SMS / Webhook / Enrichment**: configured through environment-backed settings or node data, depending on the action type.

## Lead Intake

The primary lead-acquisition path now uses `lead_gen_configs` and the [[lead-sources-ui]] workflow.

- Supported providers in the current registry: Apify Jobs, Apollo, Hunter, ProxyCurl, GitHub.
- Configs can stay manual or run on cron schedules.
- New leads are inserted with `source` populated and immediately enter the DAG through `sequencer.schedule_new_lead()`.

The older [[job-search-ui]] / [[job-search-pipeline]] path is still present for backward compatibility, but the main product surface has shifted to multi-source lead gen.

## Related Pages- [[lead-sources-ui]]
- [[canvas-editor]]
- [[sequential-builder]]
- [[leads-page]]
- [[queue-page]]
- [[approvals-page]]
- [[job-search-ui]]
- [[dispatcher]]

## Operator Surfaces Beyond the Campaign

Two surfaces now live outside any single campaign but are triggered by nodes inside one:

- **Approvals** — any lead sitting at a `human_approval` node shows up in the global [[approvals-page]] inbox until it's resolved. The lead's `current_node_id` is the pointer back into the campaign's DAG.
- **Notification channels** — Slack/email destinations configured in the Notifications tab of [[settings-page]] are the fan-out target for `action_hot_lead_alert` nodes. Scoping is global; a campaign wanting a different destination overrides it on the node via `channel_ids`.
