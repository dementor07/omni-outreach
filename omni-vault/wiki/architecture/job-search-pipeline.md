---
title: Lead Generation Pipeline (Job Search)
category: architecture
tags: [lead-gen, apify, serper, job-search, dag-injection]
sources: []
updated: 2026-04-12
---

# Lead Generation Pipeline

`backend/app/services/job_search.py`
`backend/app/routers/job_search.py`

Autonomous pipeline: scrapes job postings → finds decision-makers → upserts leads → injects into campaign DAG.

## Status: Implemented (DAG injection complete)

## Pipeline Stages

```
Apify Actor (LinkedIn Jobs scraper)
        ↓
filter_by_industry()
        ↓
SERPER Google search per company (concurrent, semaphore=3)
        ↓
upsert_leads() → INSERT INTO leads ... RETURNING id
        ↓
sequencer.schedule_new_lead(lead_id)  ← DAG entry
```

## Stage 1: Apify

`run_apify_actor(actor_id, input_payload)` — starts an Apify run, polls every 10s until `SUCCEEDED`, fetches dataset items. Raises `RuntimeError` on `FAILED/ABORTED/TIMED-OUT`.

Input shape:
```json
{ "queries": ["keyword1"], "location": "...", "maxResults": N }
```

## Stage 2: Industry Filter

`filter_by_industry(jobs, allowed)` — deduplicates by company name, keeps only companies where `job.sector` or `job.companyIndustry` matches any allowed string. Default: IT Services, Software Dev.

## Stage 3: SERPER Decision-Maker Search

`search_decision_makers(client, company_name, roles, max_per_company)` — for each role in `config.serper_roles`, queries SERPER:
```
{role} at {company_name} site:linkedin.com/in
```
Extracts LinkedIn `/in/` URLs from organic results. Handles 429 with exponential backoff (up to `MAX_RETRIES=3`). 0.5s sleep between roles.

## Stage 4: Upsert & DAG Injection

`upsert_leads(campaign_id, company, profiles)`:
- Skips leads where `linkedin_url` already exists for this campaign
- `INSERT INTO leads ... RETURNING id`
- Calls `sequencer.schedule_new_lead(str(lead_id))` → starts DAG from `trigger_start`
- Returns count of newly added leads

## Config Table

`job_search_configs`:
- `apify_actor_id` — which Apify actor to run
- `job_keywords` — list of search queries
- `job_location` — optional location filter
- `max_companies` — cap on companies after filtering
- `allowed_industries` — list of industry strings
- `serper_roles` — list of roles to search (e.g. "CEO", "CTO", "Marketing Director")
- `max_leads_per_company` — cap per company

## Runs Table

`job_search_runs`: tracks `status`, `jobs_scraped`, `companies_filtered`, `leads_found`, `leads_added`, `started_at`, `finished_at`, `error`.

## API

| Endpoint | Method | Behavior |
|----------|--------|----------|
| `/job-search/trigger` | POST | `{ campaign_id, config_id }` → fires `run_job_search()` as background task |
| `/job-search/runs` | GET | List runs (optional `campaign_id` filter) |
| `/job-search/runs/{id}` | GET | Single run detail |
| `/job-search/configs/{campaign_id}` | GET | List configs for campaign |

## Related Pages
- [[sequence-engine]]
- [[lead-generation-injection]]
- [[campaigns]]
