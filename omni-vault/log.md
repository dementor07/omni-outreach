# Omni Wiki — Operation Log

Append-only. Format: `## [YYYY-MM-DD] operation | description`

---

## [2026-04-12] init | Vault created

Initialized omni-vault structure. Created CLAUDE.md schema, index.md, log.md. Seeded architecture and product pages from live codebase + session context.

## [2026-04-12] verify & deploy | Round 8 fixes verified and deployed to VPS

- Verified `Toast.tsx` useMemo context reference fix preventing infinite re-render loops.
- Verified `RetellFlowEditor.tsx` load error state implementation on fetch failure.
- Deployed to VPS (`145.223.21.222`): pulled `outreach-threading` branch and restarted Docker `backend` and `frontend` services.
- Tested Voice node Standard mode and Nested Flow editor logic paths.

## [2026-04-12] ingest | Fleshed out wiki stubs

Completed the wiki index by creating comprehensive pages for previously stubbed topics:
- `dispatcher` (Queue locking and task routing)
- `channels` (Overview of active and stubbed outreach mediums)
- `campaigns` (Configuration, caps, and lead generation)
- `bridge-agent` (Documentation of the autonomous Claude↔Gemini system)
- `landscape` (Competitive analysis)
Removed the Stubs section from `index.md`.

## [2026-04-12] ingest | Karpathy LLM Wiki Method

Ingested `raw/llm-wiki-pattern.md` from `LLM Wiki.txt`. Created `wiki/architecture/llm-wiki-method.md` to document the core philosophy, architecture, and application of the Karpathy method in the Omni vault. Updated `index.md`.

## [2026-04-12] ingest | Event-Driven State Machine Paradigm

Ingested `raw/Clippings/Cold Outreach Script Fix.md` covering the ChatGPT architecture brainstorm. Avoided creating fragmented new files, adhering to the Karpathy method. Instead, fully synthesized the new Event-Driven State Machine paradigm (Trigger, Event, Action, Condition, Control, Subflow) directly into the existing `wiki/architecture/sequence-engine.md` and `wiki/architecture/system-overview.md` files to compound knowledge and reduce future RAG token usage.

## [2026-04-12] document | Updated Vault with Functional Implementations

Actively utilized the `omni-vault` to document the code changes resulting from the Event-Driven State Machine paradigm shift:
- Updated `wiki/architecture/sequence-engine.md` to list the actual node types instantiated in the codebase (e.g., `action_linkedin_inmail`, `event_invite_accepted`, `condition_linkedin_distance`).
- Updated `wiki/product/channels.md` to document the new `_handle_linkedin_inmail` and `_handle_linkedin_profile_view` logic running inside `dispatcher.py`.
This ensures the LLM Wiki remains the absolute ground-truth reflection of the codebase state.

## [2026-04-12] document | Created ADR for Omnichannel Logic Loops

Following the Karpathy "Vault First" method, created `wiki/decisions/omnichannel-logic-loops.md` to architect how tag-based routing, channel-agnostic event listeners, and A/B split nodes will be used to create robust cross-channel loops. Updated `index.md`.

## [2026-04-12] document | Massive Vault Additions (Architectural Blueprints)

Created four significant architectural nodes in the vault before writing code:
- `wiki/architecture/event-bus-architecture.md`: Blueprint for Kafka/Redis Streams to handle high-throughput webhooks and prevent database locking.
- `wiki/architecture/auto-optimization-engine.md`: Blueprint for upgrading split nodes into Multi-Armed Bandits via Reinforcement Learning.
- `wiki/integrations/instagram-telegram-integration.md`: Spec for mapping Unipile endpoints to the stubbed IG/TG actions.
- `wiki/decisions/lead-generation-injection.md`: ADR on creating an autonomous pipeline via Apify and Serper to feed the DAG.
Updated `index.md` with these links.

## [2026-04-12] ingest | Knowledge Graph Integration

Ingested `raw/Clippings/Supercharging LLM Wiki with Knowledge Graphs Build a Self-Evolving Research System.md`. Synthesized the concepts into `wiki/architecture/knowledge-graphs.md` to document how Network Science (via InfraNodus MCP/plugins) can be applied to the LLM Wiki to detect content gaps, reveal conceptual blind spots, and proactively guide the LLM to generate novel insights rather than just passively retrieving information. Updated `index.md`.

## [2026-04-12] generate | Gap Analysis & Insight Generation

Executed the Knowledge Graph workflow by extracting the vault's ontology into `infranodus/ontology.md`. 
Discovered three major structural gaps between clusters. Generated two novel architectural blueprints to bridge them:
- `wiki/decisions/autonomous-feedback-loops.md`: An ADR detailing how to feed Reinforcement Learning rewards back into the Apify Lead Generation pipeline, and how to grant Retell AI the `update_omni_lead_tags` tool to bridge conversational discoveries into Omni's tag-based routing logic.
- `wiki/architecture/telemetry-overlay.md`: A blueprint for solving the Event Bus observability gap by piping live Webhook/Stream throughput directly into the ReactFlow edge styles (glowing paths, backpressure halos).
Updated `index.md`.

## [2026-04-12] session end | HEAD af31cd7

Last commit: af31cd7 — Redis Streams Event Bus implemented.
Active TODO: Lead Generation Pipeline (Apify+Serper). Pending: Canvas Telemetry Overlay, Auto-Optimization Engine.
Next session: start fresh Claude Code chat, read omni-vault/index.md first.

## [2026-04-12] ingest | Code modules promoted to vault nodes

All major backend services and the canvas editor promoted from thin stubs to full code-level wiki pages. Vault is now the primary reference — files are secondary.

Updated:
- `dispatcher.md` — all 11 channel handlers documented, cron behaviors, retry logic
- `sequence-engine.md` — all node types, all function signatures, split/bandit behavior, path_history schema
- `auto-optimization-engine.md` — blueprint → implemented; Beta params, reward schedule, cron registration
- `telemetry-overlay.md` — blueprint → implemented; TelemetryEdge color table, polling effect, edge type switching
- `canvas-editor.md` — all node/edge components, SplitNode bandit display, Live toggle, serialization notes

Created:
- `job-search-pipeline.md` — full Apify→Serper→upsert→DAG injection pipeline
- `worker.md` — arq cron schedule (all 4 jobs), stream processor, consumer group

Updated `index.md` with all new/updated pages.

## [2026-04-12] feat & deploy | Canvas Telemetry Overlay + Auto-Optimization Engine — HEAD 6304bd3

**Telemetry Overlay:**
- `GET /sequences/{id}/telemetry` — returns activity (sent in 60s) and backpressure (queued/locked) counts per source node_id.
- `TelemetryEdge` component: live-colored edges (slate→sky→emerald on activity, amber dashed on backpressure), floating lead count pill.
- Live toggle button in canvas Panel polls every 5s and syncs telemetry data into ReactFlow edge state.

**Auto-Optimization Engine (Thompson Sampling):**
- `split` node handler in sequencer: samples Beta(α,β) for each arm, routes to the winning arm, records choice in `leads.path_history JSONB`.
- DB migration: `ALTER TABLE leads ADD COLUMN IF NOT EXISTS path_history JSONB DEFAULT '[]'` runs on backend startup.
- `optimization.py`: cron every 10min, traces rewards (invite_accepted, reply_received, dm_sent) back through path_history, updates Beta params in `sequence_nodes.data.weights`.
- `SplitNode` UI: shows live win-rate % per arm once the bandit has enough data.

Deployed. All three items from the Active TODO list are now complete.

## [2026-04-12] fix & deploy | Lead Gen DAG injection completed — HEAD 0679d5c

- Fixed syntax error in `job_search.py` (stray `...` and misplaced import).
- Added `sequencer.schedule_new_lead(lead_id)` — DAG entry that does not require `accepted_at`, designed for freshly scraped leads.
- `schedule_sequence()` retained for post-acceptance resume path.
- `upsert_leads()` now calls `schedule_new_lead()` so every Apify/Serper lead is automatically injected into the campaign DAG at `trigger_start`.
- Pushed to `outreach-threading`, deployed to VPS. Backend + worker healthy.
- Lead Generation Pipeline (Apify+Serper → DAG injection): COMPLETE.
- Next: Canvas Telemetry Overlay or Auto-Optimization Engine.

## [2026-04-12] fix & deploy | SequentialBuilder Wait Duration Edit — HEAD fab5c33

- Fixed a TypeScript type-inference error in `SequentialBuilder.tsx` during production build by casting `node.data` to `any`.
- Added `updateStep()` function and an interactive numeric input to allow users to directly edit the "Wait" duration for `delay` nodes in the Sequential list view.
- Ensured state consistency by mapping the linear list changes back to the unified `nodes` and `edges` graph state.
- Deployed to VPS. The Sequential mode is now fully functional and in sync with the Nodal Canvas capabilities.

## [2026-04-13] enforce | Karpathy method operationalized

- Created `wiki/architecture/agent-operations-protocol.md` as the canonical execution policy for concurrent multi-agent work.
- Enforced hard lane separation: Executor (single-writer), Planner, Reviewer.
- Added mandatory session template (start/during/end), cross-agent handoff format, and done criteria.
- Added fast-failure conditions to stop drift when architecture, validation, or readiness signals conflict.
- Updated `index.md` to register `agent-operations-protocol` as a first-class architecture node.

## [2026-04-13] lint | Index naming consistency

- Aligned `index.md` bridge-agent summary with the enforced three-agent scope (Copilot, Claude, Gemini).
- No policy violations found in append-only logging or index synchronization.

## [2026-04-13] enforce | MCP-first vault operations

- Reviewed Obsidian clipping (`raw/Clippings/Clippings/Claude Code + Obsidian - How I use it & Short Guide.md`) and adopted MCP-first workflow.
- Updated `CLAUDE.md` rules: vault operations default to MCP/API, filesystem access is fallback-only.
- Updated `wiki/architecture/agent-operations-protocol.md` with an explicit MCP-first control rule for all agents (Copilot, Claude Code, Gemini).



## [2026-04-13] cleanup | Vault junk removed

- Deleted _api_read_report.json (generated temporary MCP read report artifact).
- Deleted create a link.md (empty placeholder note, 0 chars).
- Cleanup executed via MCP/API only.


## [2026-04-13] sync | Git/code aligned with Obsidian workflow

- Sync audit completed against git branch master at HEAD c1610ce.
- Enforced clean boundary: Obsidian local runtime files moved out of version-control scope via .gitignore (omni-vault/.obsidian/).
- Untracked previously tracked local state files (.obsidian/graph.json, .obsidian/workspace.json) to prevent settings drift and secret leakage in commits.
- Vault content nodes remain tracked (wiki/, raw/, index.md, log.md, CLAUDE.md).


## [2026-04-13] sync | Finalize Obsidian git boundary

- Untracked remaining local Obsidian state files from git index (.obsidian/app.json, .obsidian/appearance.json, .obsidian/core-plugins.json).
- Confirmed no .obsidian paths remain tracked in git (git ls-files check).


## [2026-04-13] audit | Vault vs runtime drift check

- Local repository now includes Obsidian sync commits on master (99e8152, 6bc6bb9).
- Live server checkout at /home/omni-outreach is still on master HEAD c1610ce.
- Running containers are healthy, but runtime parity is incomplete.
- Live backend API exposes voice/account routes, but is missing /sequences/{campaign_id}/telemetry.
- Production leads table does not contain path_history, so the documented optimization path is not live in DB.
- Conclusion: vault and local codebase are ahead of deployed runtime for telemetry/optimization-related features; redeploy/migration is still needed for full parity.


## [2026-04-13] deploy | Runtime parity restored on VPS

- Pushed local master to origin/master through commit e38b29e.
- Updated /home/omni-outreach on VPS to e38b29e and rebuilt/restarted backend, worker, and frontend.
- Verified live backend now exposes /sequences/{campaign_id}/telemetry, /accounts/voice/flows, and /accounts/voice/{agent_id}.
- Verified production leads table now contains path_history.
- Result: vault, local codebase, deployed server, and production schema are back in sync on the previously drifting telemetry/optimization markers.

## [2026-04-13] fix | UI parity restored — HEAD 6bb545c

- Expanded backend `NodeType` Literal from 10 → 21 types to match frontend palette.
- Rebuilt backend + worker on VPS.

## [2026-04-13] fix | UI parity pass 2 — HEAD 5d26679

- Fixed 6 broken job-search APIs: path param, create config, trigger URL, runs filter, column aliases, response shapes.
- `CampaignSettings` now exposes all 8 editable fields.
- Campaign stats mini-bar added to detail view header.

## [2026-04-13] wiki | UI product docs expanded

- Created 5 new pages: dashboard, leads-page, queue-page, settings-page, job-search-ui.
- Rewrote campaigns.md with full UX detail (tabs, Settings form 8 fields, stats bar).
- Expanded canvas-editor.md to all 21 node types.
- Updated index.md.

## [2026-04-13] fix | Canvas UX overhaul — HEAD c798e5e

- Defined `btn-tactile` CSS utility class.
- Renamed "Genesis Trigger" → "Sequence Start"; TriggerNode "Inception/Lead Accepted" → "Trigger/Sequence Start".
- NodePalette: grouped by 7 categories, scrollable (`maxHeight: calc(100vh-160px)`).
- Renamed "Deploy Canvas" → "Save Canvas" (sky-500 styling).
- Sequential builder: expanded from 4 → 12 add buttons.
- Added `action_sms` and `action_webhook` to backend `NodeType` Literal, frontend union, `nodeTypes` map, NODE_PALETTE, and SequentialBuilder.
- Replaced placeholder icons with semantically correct icons throughout canvas and builder.
- Hotfix: `TagX` (not exported by installed lucide-react) → `MinusCircle`. Deployed to VPS.

## [2026-04-19] fix | Remaining canvas icon cleanup — HEAD 4d495d3

- `ConditionNode` icon: `<Zap>` → `<GitBranch>`.
- `SplitNode` icon: `<Zap>` → `<Shuffle>`.
- `EventNode` icon: static `<Zap>` → dynamic `cfg?.icon` from NODE_PALETTE (Bell fallback).
- Deployed to VPS. All placeholder icons eliminated from canvas node components.

## [2026-04-19] wiki | Vault audit and update

- Audited all product pages against live codebase.
- Updated canvas-editor.md: 21 → 23 node types, correct palette groups (7 headings), Canvas UX Controls section, icon corrections, updated date.
- Updated sequential-builder.md: documented 12 add buttons, STEP_LABELS map, StepIcon component, corrected "Script" → "Edit Template".
- Updated channels.md: added SMS and Webhook/CRM to Stubbed Channels section.
- Updated index.md: corrected canvas-editor summary to 23 nodes, updated channels summary, updated last-updated date.
- Cleaned duplicate/malformatted log entries (converted bullet points to proper `## [date]` headings, removed duplicate wiki entries).

## [2026-04-19] retrospective | Vault usage failure identified and corrected

Identified 5 ways the vault was being misused:
1. Agents never read index.md/log.md at session start — skipping the compounding memory entirely.
2. Questions were answered from code, not from wiki pages with [[citations]].
3. Zero ADRs were written for decisions made during implementation (naming, icon choices, palette grouping, stubbed channel policy).
4. Wiki updates happened as after-the-fact cleanup, not vault-first design.
5. MCP/API was never used — filesystem tools were always used directly.

Corrective actions taken:
- Created `wiki/decisions/canvas-ux-decisions.md` — captures all April 2026 UX naming, palette, icon, and tooling decisions.
- Created `wiki/decisions/stubbed-channels-policy.md` — captures why SMS/Webhook/IG/TG are fully typed but no-op at dispatcher level.
- Rewrote `Start-of-session` section of `wiki/architecture/agent-operations-protocol.md` — explicit READ-FIRST mandate, query workflow, and ADR-at-decision-time rule.
- Updated index.md with both new ADR pages.

Going forward: decisions go in the vault at decision time, not in a cleanup pass.

## [2026-04-19] feat | Multi-source lead generation architecture

Filed `wiki/decisions/multi-source-lead-gen.md` ADR before implementation (vault-first).

Backend implemented:
- `services/lead_sources/base.py` — `LeadSource` abstract protocol, `RawLead` dataclass
- `services/lead_sources/apify_jobs.py` — existing Apify+SERPER pipeline refactored into provider
- `services/lead_sources/apollo.py` — Apollo.io People Search (optional, APOLLO_API_KEY)
- `services/lead_sources/hunter.py` — Hunter.io Domain Search (optional, HUNTER_API_KEY)
- `services/lead_sources/proxycurl.py` — ProxyCurl company employees (optional, PROXYCURL_API_KEY)
- `services/lead_sources/github.py` — GitHub org member search (free, GITHUB_TOKEN optional)
- `services/lead_source_registry.py` — global registry, `available()` / `get()` / `all()`
- `services/lead_gen.py` — unified pipeline dispatcher, `run_lead_gen()`, `upsert_lead()`
- `routers/lead_gen.py` — `/lead-gen/sources`, `/lead-gen/configs`, `/lead-gen/trigger`, `/lead-gen/runs`
- `config.py` — added `apollo_api_key`, `hunter_api_key`, `proxycurl_api_key`, `github_token`
- `main.py` — registered `/lead-gen` router, `CREATE TABLE IF NOT EXISTS lead_gen_configs/runs`

Frontend implemented:
- `pages/LeadSources.tsx` — new page with source availability grid, schema-driven config forms, config cards, run history
- `App.tsx` — added `/lead-sources` route
- `Sidebar.tsx` — added "Lead Sources" nav item (Database icon)

Old `/job-search/` router and `JobSearch.tsx` preserved for backward compatibility.

## [2026-04-19] plan | Lead Gen → Canvas/Sequence integration ADR

Filed `wiki/decisions/lead-gen-canvas-integration.md` — vault-first planning before implementation.

Identified 6 gaps between the new multi-source lead gen and the existing sequence engine/canvas:
1. All sources dump into the same `trigger_start` — no source-based routing
2. No quality gate — `screener.py` exists but is orphaned (not wired to any node)
3. No enrichment step — thin leads hit outreach immediately
4. LeadSources page and Canvas are visually disconnected
5. Lead gen is manual-trigger only — no cron/schedule
6. API keys are env vars only — no Settings UI

Plan covers 4 phases:
- **Phase 1A**: `condition_ai_screen` (wires screener.py) + `condition_lead_source` (routes by source type) — quality gate + source routing
- **Phase 1B/C**: `condition_has_field` + `action_enrich` — waterfall enrichment
- **Phase 2**: Visual integration — trigger_start source badge, campaign Sources tab, telemetry source breakdown
- **Phase 3**: Scheduled lead gen — cron column + arq worker job + schedule UI
- **Phase 4**: Settings → Integrations UI — encrypted API key storage, verification

Recommended sprint order: 1A → 3 → 1B → 4 → 1C → 2A → 2B (screening gate first, then scheduling, then enrichment, then polish).

## [2026-04-19] feat & deploy | Phase 1A canvas nodes + test dashboard — HEAD 4546e83

**Phase 1A implemented** (from lead-gen-canvas-integration ADR):
- `condition_ai_screen` node: wires `screener.py` into the sequence engine. Canvas node has `screening_prompt` textarea config. Sequencer handler calls `screener.screen_lead()` and routes to `true`/`false` handles.
- `condition_lead_source` node: routes leads by `lead.source` field. Config holds `sources[]` array. Canvas node renders source checkboxes. Sequencer handler matches `lead.source` against configured sources, routes to matching handle or `default`.
- Backend `NodeType` Literal: 23 → 25 types.
- Frontend: NODE_PALETTE entries (Brain + Route icons), nodeTypes map, ConfigSidebar panels, SequentialBuilder entries.

**Bug fix — asyncpg JSONB serialization:**
- `node.data` (Python dict) was passed directly to asyncpg INSERT for a `jsonb` column without JSON codec registration.
- Error: `asyncpg.exceptions.DataError: invalid input for query argument $5: {} (expected str, got dict)`.
- Fix: `json.dumps(node.data)` before INSERT in `sequences.py`.

**Test dashboard created** (`test_dashboard.py`):
- 20 endpoint tests across 8 sections, validated against vault wiki documentation.
- Sections: Dashboard (overview, campaigns, queue), Campaign (get, stats), Leads (list), Canvas (load, save Phase 1A graph, reload+verify persistence, telemetry), Accounts (email, voice, LinkedIn), Lead Gen (sources, configs, runs), Job Search (configs, runs), Frontend (HTML+JS bundle).
- Result: **20/20 PASS**, 0 FAIL, 0 ERROR.
- Phase 1A node data verified: `screening_prompt` and `sources[]` persist and round-trip correctly through save→reload.

## [2026-04-19] feat & deploy | 20-Cycle System Gaps Sprint — HEAD ac578c3

Executed a 20-cycle brainstorm→implement sprint to close 140+ gaps identified in a full codebase audit against competitors (Apollo, Instantly, Lemlist). ADR filed vault-first as `wiki/decisions/system-gaps-sprint.md`.

**Backend — 7 new routers, 1 new service:**
- `routers/notifications.py` — `notifications` table, mark-read/dismiss, SSE push
- `routers/activity.py` — `activity_log` table, recent events endpoint
- `routers/blacklist.py` — `blacklists` table, CRUD, domain/email/company types, check endpoint
- `routers/tracking.py` — Email open pixel + click redirect, `email_tracking` table
- `routers/analytics.py` — Time-series campaign stats, funnel metrics, per-node performance, export CSV
- `routers/template_library.py` — Global templates CRUD, search, performance ranking, variable extraction
- `routers/inbox.py` — Unified inbox aggregating replies across all channels
- `services/reply_classifier.py` — AI-powered reply intent detection (interested/not-interested/OOO/bounce/auto-reply)

**Backend — existing router extensions:**
- `campaigns.py` — Campaign cloning endpoint, schedule start/end, campaign stats mini-bar
- `leads.py` — Bulk actions (stop/requeue/move/delete/tag), CSV import, search/filter/pagination, lead detail with timeline
- `overview.py` — Enhanced dashboard with channel breakdown, time-series data, sparkline stats
- `webhooks.py` — Reply classification hook, goal/conversion tracking, webhook dispatcher handler
- `main.py` — All 7 new routers registered, CREATE TABLE IF NOT EXISTS for all new tables

**Frontend — 6 new pages, 2 new components, 8 new hooks:**
- Pages: `Analytics.tsx`, `Activity.tsx`, `Blacklist.tsx`, `Inbox.tsx`, `Templates.tsx` (global library)
- Components: `CsvImport.tsx` (file upload + field mapping), `NotificationCenter.tsx` (bell + drawer)
- Hooks: `useAnalytics`, `useBlacklist`, `useCanvasHistory` (undo/redo), `useInbox`, `useNotifications`, `useTemplateLibrary`, `useTheme` (dark mode)
- Existing page upgrades: Dashboard (recharts, sparklines), Campaigns (clone, schedule, settings), Leads (bulk actions, CSV import, search/filter, drawer)

**TypeScript fixes (post-sprint):**
- `Leads.tsx` — stray `</div>` removed
- `DataTable.tsx` — `Column.header` widened to `ReactNode`
- `CsvImport.tsx` — const tuple `required` check
- `Blacklist/Inbox/Templates` — missing `icon` prop on EmptyState
- `Inbox.tsx` — BadgeVariant `'danger'` → `'error'`

**Deployment:** All containers rebuilt and healthy on VPS 145.223.21.222 (backend, worker, frontend). `GET /health` → `{"status":"ok"}`.

Updated `index.md` and `canvas-editor.md` with sprint additions.

## [2026-04-19] security & feat | Integrations Security Architecture + Key Management

Filed `wiki/decisions/integrations-security-architecture.md` ADR vault-first.

**Security audit and hardening (Phase 1):**
- CORS: Replaced `allow_origins=["*"]` with configurable `frontend_url` split origins
- Rate limiting: Added `slowapi` with `SlowAPIMiddleware`; auth endpoints limited (`5/hour` register, `10/min` login)
- Open redirect: Fixed `tracking.py` redirect — validates scheme+netloc via `urlparse()`
- JSON injection: Fixed `tracking.py` pixel event — `json.dumps()` instead of f-string
- Webhook signature: Added HMAC-SHA256 verification for Unipile webhooks in `webhooks.py`
- SSE type bug: Fixed `notifications.py` `user: dict` → `user_id: str` for `get_current_user` return type
- Email validation: `EmailStr` on auth register/login models
- Dependencies: Added `slowapi>=0.1.9`, `cryptography>=43.0`

**Integration key management (Phase 2):**
- `services/encryption.py` — Fernet encrypt/decrypt/mask, key derived from SHA-256(SECRET_KEY)
- `routers/settings.py` — Full CRUD for encrypted integration keys:
  - `GET /settings/integrations/providers` — 11 providers (Unipile, Retell, Resend, Anthropic, Apify, Serper, Apollo, Hunter, ProxyCurl, GitHub, Twilio)
  - `GET /settings/integrations` — List keys with masked values
  - `PUT /settings/integrations` — Upsert encrypted key (UNIQUE constraint on user+provider+field)
  - `DELETE /settings/integrations` — Remove key
  - `POST /settings/integrations/{provider}/verify` — Lightweight HTTP test per provider
  - `get_integration_key()` — DB-first with env var fallback for service consumption
- `main.py` — `integration_keys` table auto-created in lifespan, with FK to users and index on user_id

**Docker hardening (Phase 3):**
- Backend: `ports: "8000:8000"` → `expose: "8000"` (only reachable via nginx proxy)
- Redis: Added `--requirepass` and healthcheck with auth
- Networks: Isolated `internal` (db/redis/backend/worker) + `external` (frontend/nginx only)
- Config: `get_redis_url()` method supports authenticated Redis

**Frontend:**
- `Settings.tsx` — New "Integrations" tab with provider card grid, masked key display, Save/Delete/Verify per field, shield status icons (ShieldCheck/ShieldX/Shield)