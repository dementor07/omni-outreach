---
title: ADR — Lead Generation & Injection Pipeline
category: decisions
tags: [ADR, apify, serper, scraping, injection, triggers]
sources: []
updated: 2026-04-12
---

# ADR: Lead Generation & Injection Pipeline

**Date:** 2026-04-12
**Status:** Accepted

## Context
Omni requires a steady stream of highly targeted prospects to feed the DAG [[sequence-engine]]. Relying solely on manual CSV uploads creates a massive friction point for users. We need an autonomous pipeline that scrapes, enriches, and injects leads directly into the start of a campaign graph.

## Decision
We will build a native orchestration layer that controls third-party scrapers (Apify) and enrichment APIs (Serper), executing them on cron schedules to create an infinite, autonomous lead loop.

### 1. Job Search Configurations
Users define a `job_search_configs` record attached to a campaign.
- **Target**: e.g., "Software Engineers in San Francisco".
- **Filters**: "Companies hiring for React", "Exclude staffing agencies".
- **Schedule**: e.g., "Run every Tuesday at 9 AM".

### 2. The Orchestration Loop (`job_search.py`)
1. **Scraping**: The backend triggers an Apify actor (e.g., `curious_coder/linkedin-jobs-scraper`) via API.
2. **Filtering**: The raw job listings are parsed. We extract the hiring company.
3. **Enrichment**: We use Serper (Google Search API) or an Apollo.io API bridge to find the specific decision-makers at that company (e.g., "VP of Engineering at [Company Name]").
4. **Injection**: The enriched profiles are mapped to our `leads` schema and inserted into the database.

### 3. The Trigger Action (`trigger_start`)
When a lead is successfully injected into the database via this pipeline:
1. `leads.source` is set to `job_search`.
2. The lead is immediately passed to `sequencer.schedule_sequence(lead_id)`.
3. The sequencer locates the `trigger_start` node for the associated campaign and pushes the lead down the DAG.

## Consequences
- **Pros**: Creates a true "Set and Forget" system. A user can design a canvas flow, set a scraping config, and Omni will continuously hunt for leads, enrich them, and sequence them forever without human intervention.
- **Cons**: High risk of garbage data (bad scrapes) polluting the DAG. We will need to implement a "Screening Node" (e.g., `condition_ai_qualified`) immediately after `trigger_start` where Claude reviews the scraped lead profile and decides whether to route them to the `True` (Outreach) or `False` (Discard) branch.

## Related Pages
- [[campaigns]]
- [[sequence-engine]]
