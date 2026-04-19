---
title: Job Search UI
category: product
tags: [job-search, UI, Apify, Serper, lead-generation, configs, runs]
sources: []
updated: 2026-04-13
---

# Job Search UI

**Route:** `/job-search`  
**File:** `frontend/src/pages/JobSearch.tsx`

Autonomous lead generation control panel. Operators configure job-search scraping criteria, trigger runs, and inspect run history here. The pipeline injects discovered leads directly into the parent campaign's sequence. See also: [[job-search-pipeline]].

## Page Layout

Two main panels, switching on `selectedCampaignId` state:

1. **Left/top: Campaign selector + Config list**
2. **Right/bottom: Run History Panel** (conditionally rendered when a config is selected)

## Campaign Selector

Dropdown (`<select>`) pulling from `GET /campaigns`. The whole page is inert until a campaign is chosen — no config operations are possible without setting campaign context.

## Config List

Data: `GET /job-search/configs/{campaign_id}`  
Returns array of `JobSearchConfig`:

```ts
interface JobSearchConfig {
  id: string
  campaign_id: string
  keywords: string[]   // stored as job_keywords in DB
  location: string     // stored as job_location in DB
  roles: string[]      // stored as serper_roles in DB
  is_active: boolean   // stored as is_enabled in DB
  created_at: string
}
```

Note: backend aliases DB column names → frontend field names via `_CONFIG_COLS` SQL fragment.

Each config card shows keywords, location, roles (as tags), creation date, and an **▶ Run** button.

### Selecting a Config

Clicking a card sets `selectedConfigId`. This opens the `RunHistoryPanel` on the right.

### Create Config Modal

Triggered by the "New Config" / `+` button. Fields:
- Keywords — comma-separated text → split into `string[]`
- Location — plain text
- Roles — comma-separated text → split into `string[]`

`POST /job-search/configs` with `{ campaign_id, keywords, location, roles }`.  
On success: invalidates configs query, closes modal.

## Run Trigger

The "▶" Run button fires:  
`POST /job-search/trigger` with `{ campaign_id, config_id }`.

The backend enqueues an arq task (see [[worker]]) that calls Serper → Apify → upserts leads → injects into DAG. The button is disabled while `runMutation.isPending`.

## Run History Panel

Opens when a config card is selected. Data:  
`GET /job-search/runs?config_id={configId}`

Returns array of `JobSearchRun`:

```ts
interface JobSearchRun {
  id: string
  config_id: string
  status: 'running' | 'done' | 'completed' | 'failed' | 'pending'
  leads_found: number
  started_at: string
  completed_at: string | null   // DB: finished_at aliased by backend
  error_message: string | null  // DB: error aliased by backend
}
```

Note: backend converts `status='done'` → `'completed'` and aliases `finished_at` → `completed_at`, `error` → `error_message`.

### Run Cards

Each run shows:

| Field | Display |
|-------|---------|
| Status | Badge using `runStatusVariant` map: `pending→muted`, `running→info`, `done/completed→success`, `failed→error` |
| Leads found | Integer count |
| Started | `started_at` formatted |
| Completed | `completed_at` or `—` |
| Error | Rose-coloured text if `error_message` present |

## API Surface

| Action | Endpoint |
|--------|----------|
| List configs | `GET /job-search/configs/{campaign_id}` |
| Create config | `POST /job-search/configs` |
| Trigger run | `POST /job-search/trigger` |
| List run history | `GET /job-search/runs?config_id=…` |

## Known Gaps (as of 2026-04-13)

- No config edit UI — keywords, location, roles are immutable after creation
- No config delete endpoint (`DELETE /job-search/configs/{id}` not implemented)
- No `is_active` toggle — configs cannot be enabled/disabled from the UI

## Related Pages

- [[job-search-pipeline]]
- [[campaigns]]
- [[worker]]
