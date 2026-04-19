---
title: "ADR: Multi-Source Lead Generation Architecture"
category: decisions
tags: [lead-gen, apollo, hunter, proxycurl, github, apify, provider-pattern]
sources: []
updated: 2026-04-19
---

# ADR: Multi-Source Lead Generation Architecture

## Status
Accepted — April 2026

## Context

The current lead generation pipeline (`services/job_search.py`) is a single hardcoded path:
**Apify LinkedIn Jobs → Industry filter → SERPER decision-maker search → upsert leads**

This is too narrow. B2B leads come from many sources:
- Company databases (Apollo, PDL, Coresignal)
- Email finders (Hunter.io, Snov)
- LinkedIn profile scrapers (ProxyCurl)
- Job posting signals (Apify, Coresignal)
- Developer targeting (GitHub)
- Funding signals (Crunchbase)
- Intent signals (Lusha, Bombora)

The architecture must support adding/enabling new sources without touching the core pipeline. Optional integrations (Apollo, Hunter, ProxyCurl) should be pluggable — enabled only when the user provides an API key.

## Research Summary

From the April 2026 landscape analysis:

| Source | Type | Best For | Cost |
|--------|------|----------|------|
| Apify (Jobs) | Job posting scraper | Company discovery | Pay-per-run |
| SERPER | Google search API | Decision-maker discovery | Pay-per-query |
| Apollo.io | Contact database | Comprehensive B2B enrichment | $49/mo+ |
| Hunter.io | Email finder | Email discovery + verification | $34/mo+ |
| ProxyCurl | LinkedIn scraper | Profile + company enrichment | $49/mo+ |
| GitHub | Developer profiles | Developer-first company targeting | Free |
| Crunchbase | Company + funding | Funding-stage targeting | $500/mo+ |
| PDL | Bulk enrichment | Enterprise scale enrichment | $500/mo+ |

## Decision

### 1. Provider Protocol

All lead sources implement a shared abstract interface:

```python
class LeadSource(ABC):
    source_type: str       # class constant, unique identifier
    display_name: str      # shown in UI
    
    @property
    def is_available(self) -> bool: ...  # False if API key not set
    
    async def search(self, config: dict) -> list[RawLead]: ...
    
    def config_schema(self) -> dict: ...  # JSON Schema for UI form generation
```

`RawLead` is a normalised dataclass — every source must output the same shape.

### 2. Source Registry

`services/lead_source_registry.py` holds a registry of all registered providers. The registry:
- Returns only `available` sources (those with API keys configured)
- Never throws if a source is unconfigured — it just reports `is_available = False`

### 3. Unified DB Tables

New tables instead of Apify-specific `job_search_configs`:

```sql
lead_gen_configs (
  id, campaign_id, source_type TEXT, config JSONB, is_enabled, created_at
)
lead_gen_runs (
  id, campaign_id, config_id, source_type TEXT, status TEXT,
  leads_found INT, leads_added INT, started_at, finished_at, error TEXT, meta JSONB
)
```

The old `job_search_configs` / `job_search_runs` tables remain for backward compatibility; the new API router `/lead-gen/` uses the new tables.

### 4. Sources to Implement (Phase 1)

**Core (always available, no extra API key beyond existing):**
- `apify_jobs` — existing Apify + SERPER logic, extracted to provider class
- `serper_search` — standalone SERPER-only search by role + domain

**Optional (require user-provided API key):**
- `apollo` — Apollo People Search + Org Search API
- `hunter` — Hunter.io Domain Search
- `proxycurl` — ProxyCurl LinkedIn profile + company employee lookup
- `github` — GitHub org member search (free, just uses GITHUB_TOKEN for higher rate limits)

**Phase 2 (later):**
- `crunchbase` — funded company targeting
- `pdl` — bulk enrichment
- `lusha` — buying signals
- `coresignal` — web-scale employee database

### 5. Optional Integration Pattern

Optional integrations:
- Have `is_available` check config for their API key
- Are shown in the Lead Sources UI as "Coming soon" / "Not configured" if key is missing
- Require the user to enter the key in Settings → Integrations
- Never error hard if unconfigured — they just report `available: false`

### 6. Frontend Lead Sources Page

Replaces the current "Job Search" page:
- Source cards grid showing all registered sources with status badge (active/not configured)
- Per-source config creation form (fields differ per source)
- Unified run history table with `source_type` badge
- Campaign selector at top

The page DOES NOT duplicate the canvas. The canvas shows what happens after a lead enters. The Lead Sources page shows how leads get IN.

## Consequences

### Positive
- Adding a new source = one new file + one registry.register() call
- Optional integrations don't break existing pipelines
- `source` field on the `leads` table already exists — now properly populated per provider
- UI clearly shows all available and potential lead gen sources

### Pending Work
- Phase 2 sources (Crunchbase, PDL, Lusha)
- Waterfall enrichment mode (try Apollo, fall back to Hunter, fall back to SERPER)
- "Coming soon" badge in UI for unconfigured optional sources
- Rate limit backpressure per source (different limits per provider)

## Related Pages
- [[job-search-pipeline]] — superseded by this architecture
- [[channels]] — sources feed leads into the campaign DAG the same way job search did
- [[dispatcher]] — downstream consumer of upserted leads
- [[stubbed-channels-policy]] — parallel pattern: wire fully, stub execution later
