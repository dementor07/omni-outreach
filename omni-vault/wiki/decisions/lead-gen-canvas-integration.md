---
title: "ADR: Lead Gen → Canvas/Sequence Integration Plan"
category: decisions
tags: [lead-gen, canvas, sequence-engine, screening, enrichment, integration]
sources: [multi-source-lead-gen, lead-generation-injection, sequence-engine, canvas-editor]
updated: 2026-04-21
---

# ADR: Lead Gen → Canvas/Sequence Integration Plan

## Status
Accepted — implemented across 2026-04-19 to 2026-04-21

## Context

Multi-source lead gen (5 providers, registry, LeadSources UI) was shipped on 2026-04-19. But the connection between "how leads get IN" and "what happens to them" is invisible:

1. **All sources dump into the same `trigger_start`** — no way to route Apollo leads differently from GitHub leads.
2. **No quality gate** — scraped leads from any source hit the outreach DAG immediately. The lead-generation-injection ADR explicitly warned: *"We will need to implement a Screening Node (`condition_ai_qualified`) immediately after `trigger_start`."* The `screener.py` service exists but is orphaned — not wired to any node.
3. **No enrichment step** — GitHub gives name + maybe email, Hunter gives email but no LinkedIn. There's no canvas node to fill missing fields before outreach.
4. **LeadSources page and Canvas are disconnected** — user configures sources on one page, designs sequences on another, with zero visual link.
5. **Lead gen is manual-trigger only** — no cron/schedule, no auto-run.
6. **API keys are env vars only** — no Settings UI to manage them.

## Decision

## Implementation Status (2026-04-21)

### Shipped

- **Phase 1A**: `condition_ai_screen` and `condition_lead_source` are live in the backend `NodeType`, sequencer logic, canvas palette, and sequential builder.
- **Phase 1B**: `condition_has_field` is live for immediate field-presence routing.
- **Phase 1C**: `action_enrich` is live. `LeadSource.enrich()` and `supports_enrichment` now exist in the provider protocol, and Apollo, Hunter, and ProxyCurl implement enrichment.
- **Phase 2A**: `trigger_start` shows campaign source counts and scheduled-source counts, with a direct path into [[lead-sources-ui]].
- **Phase 2B**: canvas Live mode injects `sources_recent` telemetry into `trigger_start` so intake volume is visible in the graph itself.
- **Phase 3**: scheduled lead gen is live via `cron_schedule`, `last_run_at`, `triggered_by`, `croniter`, and the worker's `cron_lead_gen` job.
- **Phase 4**: integration key management landed through [[integrations-security-architecture]] and the expanded [[settings-page]] integrations tab, giving the lead-source providers DB-backed encrypted key storage with env fallback.

### Outcome

Lead intake is no longer visually or operationally disconnected from campaign execution. Users can configure sources, schedule them, inspect runs inside the campaign, and route/screen/enrich leads directly inside the sequence graph.

### Phase 1: New Canvas Nodes (4 nodes)

#### 1.1 `condition_ai_screen` — AI Screening Gate

| Field | Value |
|-------|-------|
| Category | Conditions |
| Component | `ConditionNode` |
| Handles | True (ACCEPT) / False (REJECT) |
| Config | `screening_prompt` (textarea in ConfigSidebar) |
| Backend handler | `screener.screen_lead(lead.headline, node.data.screening_prompt)` |

**Sequencer logic** in `queue_next_nodes()`:
```
elif node_type == "condition_ai_screen":
    from app.services.screener import screen_lead
    prompt = (node["data"] or {}).get("screening_prompt", "")
    verdict = await screen_lead(lead.get("headline", ""), prompt)
    branch = "true" if verdict == "ACCEPT" else "false"
    await queue_next_nodes(lead_id, target_id, branch, accumulated_delay)
```
This is **immediate** (not parking) — Haiku responds in <1s. The lead either continues to outreach or gets discarded/tagged.

**Recommended canvas pattern:**
```
trigger_start → condition_ai_screen → (True) action_linkedin_invite
                                    → (False) action_add_tag("rejected") → end
```

#### 1.2 `condition_lead_source` — Source-Based Router

| Field | Value |
|-------|-------|
| Category | Conditions |
| Component | `ConditionNode` (multi-handle variant) |
| Handles | One per source type configured, plus `default` fallback |
| Config | `sources: string[]` — which source types to branch on |
| Backend handler | Reads `lead.source`, routes to matching handle |

**Sequencer logic:**
```
elif node_type == "condition_lead_source":
    source_val = lead.get("source", "")
    configured = (node["data"] or {}).get("sources", [])
    branch = source_val if source_val in configured else "default"
    await queue_next_nodes(lead_id, target_id, branch, accumulated_delay)
```

This enables: Apollo leads → aggressive multi-channel, GitHub leads → soft developer email, Apify leads → screening first.

#### 1.3 `action_enrich` — Lead Enrichment Action

| Field | Value |
|-------|-------|
| Category | Actions |
| Component | `ActionNode` |
| Config | `enrich_source: string` (which provider to use), `fields: string[]` (what to fill) |
| Backend handler | Calls the specified lead source's enrichment path to fill missing fields |

**Dispatcher handler:**
Enrichment is async (API call). The dispatcher:
1. Picks the configured enrichment source
2. Calls a new `enrich_lead()` method on the provider
3. Updates the `leads` row with filled fields
4. Marks task `sent`

This requires adding an `enrich(lead_data) -> RawLead` method to the `LeadSource` ABC (optional, default raises NotImplementedError). ProxyCurl and Apollo can implement it. 

**Waterfall variant (Phase 2):** Chain multiple `action_enrich` nodes with `condition_has_email` / `condition_has_linkedin` between them to build a waterfall.

#### 1.4 `condition_has_field` — Field Presence Check

| Field | Value |
|-------|-------|
| Category | Conditions |
| Component | `ConditionNode` |
| Handles | True / False |
| Config | `field: string` — which lead field to check (email, linkedin_url, headline, company) |

**Sequencer logic:**
```
elif node_type == "condition_has_field":
    field_name = (node["data"] or {}).get("field", "email")
    has_value = bool(lead.get(field_name))
    branch = "true" if has_value else "false"
    await queue_next_nodes(lead_id, target_id, branch, accumulated_delay)
```

This is the building block for waterfall enrichment:
```
trigger_start → condition_has_email → (False) action_enrich(hunter) → condition_has_email → (False) action_enrich(apollo) → ...
                                    → (True) action_email
```

### Phase 2: Canvas ↔ Lead Sources Visual Link

#### 2.1 `trigger_start` Node Enhancement

The `TriggerNode` component gains a small "Sources" badge showing the count of active lead_gen_configs for that campaign. Clicking it navigates to `/lead-sources`.

**Data flow:** Campaign detail page already fetches campaign ID. The TriggerNode fetches `GET /lead-gen/configs/{campaignId}` to show the count.

#### 2.2 Campaign Detail — Sources Tab

Add a lightweight "Sources" tab to the campaign detail view (alongside Leads/Queue/Sequence/Settings). This tab:
- Shows the same config cards from LeadSources.tsx, filtered to this campaign
- Allows triggering runs and viewing history without leaving the campaign
- Quick-link to the full LeadSources page

#### 2.3 Telemetry Overlay — Source Badges

When Live mode is active on the canvas, the `TriggerNode` shows a small animated counter of "leads injected in last 60s" grouped by source. This piggybacks on the existing `/sequences/{id}/telemetry` endpoint — we just need to extend the query to include source breakdown.

### Phase 3: Scheduled Lead Gen

#### 3.1 Cron Column on `lead_gen_configs`

```sql
ALTER TABLE lead_gen_configs
  ADD COLUMN cron_schedule TEXT DEFAULT NULL,
  ADD COLUMN last_run_at TIMESTAMPTZ DEFAULT NULL;
```

- `cron_schedule`: standard cron expression (e.g., `0 9 * * 1-6` = 9 AM Mon-Sat)
- `NULL` means manual-trigger only (current behavior)

#### 3.2 Worker Cron Job

Add to the arq worker schedule:
```python
async def cron_lead_gen(ctx):
    """Runs every 5 minutes. Fires any lead_gen_configs whose cron_schedule is due."""
```

Uses `croniter` to check if `last_run_at + schedule` <= now. If so, dispatches `run_lead_gen()` and updates `last_run_at`.

#### 3.3 UI Additions

- LeadSources config card gains a "Schedule" section: cron dropdown (Every day, Every weekday, Weekly, Custom) + time picker
- Run history shows "triggered by: manual | schedule"

### Phase 4: Settings → Integrations

#### 4.1 API Key Management UI

New section in Settings page: "Integrations"

| Integration | Key Field | Status Check |
|-------------|-----------|-------------|
| Apollo.io | `apollo_api_key` | Verifies via `GET /api/v1/auth/health` |
| Hunter.io | `hunter_api_key` | Verifies via `GET /v2/account` |
| ProxyCurl | `proxycurl_api_key` | Verifies via `GET /api/credit-balance` |
| GitHub | `github_token` | Verifies via `GET /user` |

Keys are stored as encrypted values in a new `integrations` table (NOT in config.py env vars, which remain as fallback). The lead source registry checks DB first, env second.

#### 4.2 Backend

```sql
CREATE TABLE integrations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  key_name TEXT UNIQUE NOT NULL,
  encrypted_value TEXT NOT NULL,
  verified_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);
```

New router: `GET /settings/integrations`, `PUT /settings/integrations/{key_name}`, `DELETE /settings/integrations/{key_name}`.

Encryption: use Fernet symmetric encryption with a `ENCRYPTION_KEY` env var.

## Implementation Order

```
Phase 1A — condition_ai_screen + condition_lead_source     [HIGH — unlocks quality gate + source routing]
Phase 1B — condition_has_field                              [MEDIUM — enables waterfall logic]
Phase 1C — action_enrich                                    [MEDIUM — requires LeadSource.enrich() method]
Phase 2A — trigger_start enhancement + Sources tab          [LOW — visual polish]
Phase 2B — telemetry source badges                          [LOW — telemetry nice-to-have]
Phase 3  — scheduled lead gen (cron)                        [HIGH — "set and forget" promise]
Phase 4  — Settings integrations UI                         [MEDIUM — currently env vars work]
```

**Recommended sprint order:** 1A → 3 → 1B → 4 → 1C → 2A → 2B

Rationale: AI screening gate is the most critical (stops garbage leads from polluting sequences). Scheduled lead gen is next (enables the "autonomous pipeline" vision). Enrichment and visual polish can follow.

## Files to Create/Modify

### Phase 1A (AI Screen + Source Router)

**Backend:**
- `sequences.py` — add `condition_ai_screen`, `condition_lead_source` to `NodeType` Literal
- `sequencer.py` — add handlers in `queue_next_nodes()` for both new node types
- `sequencer.py` — add `condition_has_field` handler  
- `sequencer.py` — add `condition_ai_screen` to `evaluate_conditions()` (though it's immediate, not parking)

**Frontend:**
- `Campaigns.tsx` — add to `NODE_PALETTE`, `nodeTypes` map, palette groups
- `Campaigns.tsx` — add ConfigSidebar fields for `condition_ai_screen` (screening prompt textarea) and `condition_lead_source` (source selector checkboxes)
- `SequentialBuilder.tsx` — add to `STEP_LABELS`, `StepIcon`, add buttons

### Phase 1C (Enrichment)

**Backend:**
- `lead_sources/base.py` — add `async def enrich(self, lead_data: dict) -> RawLead` with default `NotImplementedError`
- `lead_sources/apollo.py` — implement `enrich()` (People Enrichment API)
- `lead_sources/proxycurl.py` — implement `enrich()` (Profile Lookup API)
- `dispatcher.py` — add `_handle_enrich()` handler
- `sequences.py` — add `action_enrich` to `NodeType`
- `sequencer.py` — action_enrich queues like any other action

**Frontend:**
- Same pattern: palette + ConfigSidebar for enrichment source selector

### Phase 3 (Scheduled)

**Backend:**
- `main.py` — ALTER TABLE add cron columns
- `worker/tasks.py` — add `cron_lead_gen` job
- `routers/lead_gen.py` — add `PATCH /configs/{id}` for schedule update

**Frontend:**
- `LeadSources.tsx` — schedule UI in config card

### Phase 4 (Settings)

**Backend:**
- `main.py` — CREATE TABLE integrations
- `routers/settings.py` — integration CRUD endpoints
- `services/lead_source_registry.py` — check DB before env for API keys

**Frontend:**
- `Settings.tsx` — Integrations tab

## Consequences

### Positive
- AI screening prevents garbage leads from reaching outreach channels
- Source-based routing enables tailored sequences per lead origin
- Enrichment fills gaps before outreach (no more "Dear [blank]" emails)
- Scheduled runs complete the "set and forget" vision
- Visual integration makes the system legible end-to-end

### Risks
- `condition_ai_screen` adds ~1s per lead (Haiku call). For batch imports of 500+ leads, this could queue up. Mitigation: process screening asynchronously via queue, not inline in `queue_next_nodes()`.
- Multi-handle `condition_lead_source` requires frontend changes to `ConditionNode` (currently only True/False). May need a new component `RouterNode` with dynamic handles.
- Enrichment costs money per call. Need clear UI feedback on credit usage.

## Related Pages
- [[multi-source-lead-gen]] — provider architecture this builds on
- [[lead-generation-injection]] — original ADR, screening node predicted here
- [[sequence-engine]] — core traversal logic being extended
- [[canvas-editor]] — UI surface for new nodes
- [[auto-optimization-engine]] — bandit can optimize screening thresholds
- [[dispatcher]] — new enrichment handler needed
- [[lead-sources-ui]] — canonical intake surface now linked into the campaign and trigger UX
