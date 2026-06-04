# Omni Wiki — Operation Log

Append-only. Format: `## [YYYY-MM-DD] operation | description`

---

## [2026-06-01] v2-pipeline-watch | Apify source fan-out restored on VPS

Caught up from Claude's v2 work on `/home/omni-v2`:
- v2 stack is running under `docker compose -p omni-v2 -f docker-compose.v2.yml`.
- `muscle-v2` is the Rust v0.2 consumer group for `outreach.commands`.
- `muscle-v2` fixes already present: `MAX_POLL_INTERVAL` raised to 60m, group isolated as `muscle-v2`, Apify poll cap raised to 45m, `auto.offset.reset=earliest`, and Postgres `processed_commands` ledger dedupe.

Live pipeline state observed:
- Fresh lead `ef904d21-a797-4d71-857e-8f94c180bf2e` fired `source.linkedin_jobs`.
- Rust command `8526a9be-ed04-44fb-b5c0-a6624f86f9be` ran Apify actor `TRqkOdSRBLMin2jH1`.
- Apify completed successfully: `jobs_returned=100`, `companies_extracted=78`.
- Initial transition was missing `lead_mutations`, so `flow.for_each` saw empty `companies` and walked to `flow.end`.

Fix applied:
- Rebuilt and redeployed `orchestrator-v2` with the DAG-aware Flink orchestrator that forwards `metadata.workspace_id` and `metadata.lead_mutations`.
- Removed the PyFlink-incompatible `KafkaRecordSerializationSchemaBuilder.set_validation_mode(...)` call.
- Canceled stale Flink job `36080ae67f4b99cc4ae04b3d13757054`.
- New Flink job `90fc862392af5c3119a33794e4ea41ef` is running.
- Replayed the corrected transition for command `8526a9be...` into `outreach.transitions`.

Result after replay:
- Parent lead now has 78 companies in `custom_fields.companies`.
- `flow.for_each` spawned the configured cap of 50 children.
- Company filter / `ai.screen_company` / `source.serper_people` branches are actively flowing through `muscle-v2`.
- Contacts are not yet created at the tracking moment; the pipeline is still draining through screening and people search.

## [2026-05-17] sota-backend | Brain/Muscle/Spine/Lungs stack deployed on VPS

Deployed the agreed SOTA backend stack to `srv1575227.hstgr.cloud`: FastAPI control plane, Rust execution engine, Redpanda event spine, Flink journey orchestrator, DragonflyDB memory layer, Postgres sink, nginx edge.

Verified on the VPS:
- `execution-engine` consumes `outreach.commands`, publishes `outreach.results`, preserves metadata, manually commits offsets, and dead-letters schema failures.
- `journey-orchestrator` is submitted to the Flink session cluster and emits timer transitions into `outreach.transitions`.
- DragonflyDB replaced the Redis image while keeping the `redis` service name for compatibility.
- Public health and direct backend health are green; backend ruff, compileall, and pytest pass.

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

## [2026-04-19] infra | Production Hardening Sprint — HEAD 7f672aa

Closed all infrastructure gaps identified in vault audit. Everything except single-VPS limitation addressed.

**Alembic migrations:**

- `alembic.ini`, `alembic/env.py`, `alembic/script.py.mako` — full setup with sync DSN builder
- `alembic/versions/001_initial_schema.py` — consolidated all 22+ tables into one baseline migration
- Added `psycopg2-binary>=2.9` for Alembic's sync driver
- Stamped existing production DB at `001 (head)`

**Structured JSON logging:**

- `app/logging_config.py` — `JSONFormatter` class, `setup_logging()`, `get_logger(name)`
- All log output now structured JSON (timestamp, level, logger, message)
- Verified in production: `docker logs` shows proper JSON format

**Nginx hardening (`frontend/nginx.conf` rewrite):**

- Gzip: level 5, all relevant MIME types
- Security headers: X-Frame-Options SAMEORIGIN, X-Content-Type-Options nosniff, X-XSS-Protection, Referrer-Policy strict-origin-when-cross-origin, Permissions-Policy (camera/mic/geo denied)
- Docker DNS resolver `127.0.0.11 valid=10s` for variable proxy_pass
- `rewrite ^/api/(.*) /$1 break;` + variable `proxy_pass` (fixes path stripping with resolver)
- Static `/assets/` caching: 1 year, immutable
- SSE/WebSocket headers: Upgrade, Connection pass-through
- HTTPS server block ready (commented out, needs domain + cert)

**Docker hardening:**

- Backend Dockerfile: non-root user (`app:app`), `curl` for healthcheck, copies alembic files
- `docker-compose.yml`: backend healthcheck (30s interval, 15s start), frontend depends_on healthy, cert volume mount
- Redis password default aligned: `config.py` `redis_password="changeme"` matches `docker-compose.yml` `${REDIS_PASSWORD:-changeme}`

**CI/CD pipeline (`.github/workflows/ci.yml`):**

- Jobs: lint (ruff) → test (postgres+redis services, pytest) → build (docker) → deploy (appleboy/ssh-action)
- Deploy only on master push, uses `VPS_HOST` + `VPS_SSH_KEY` secrets
- Runs `alembic upgrade head` post-deploy

**Test suite foundation:**

- `backend/tests/conftest.py` — ASGI transport fixtures with httpx.AsyncClient
- `backend/tests/test_health.py` — smoke tests (health, register+login, unauthenticated 401/403)
- `pyproject.toml` — pytest (asyncio_mode=auto) + ruff (py312, line-length=120) config

**SSL infrastructure:**

- `scripts/ssl-setup.sh` — Certbot standalone, copies certs, cron renewal
- `certs/.gitkeep` — placeholder for volume mount

**Bugs fixed during deploy:**

- nginx 502 on `/api/` — variable proxy_pass wasn't stripping prefix → added rewrite rule
- Redis health "Authentication required" — `config.py` defaulted to empty password while docker-compose defaulted to `changeme`
- Alembic `ModuleNotFoundError: psycopg2` — added `psycopg2-binary` to requirements

**Final state:** All containers healthy, `/api/health` → `{"status":"ok","checks":{"api":"ok","db":"ok","redis":"ok"}}`, Alembic at `001 (head)`, security headers verified, asset caching confirmed (1y immutable).

## [2026-04-21] security | Suspicious-site false-positive mitigation — HEAD 4706ffe

Started from `omni-vault/index.md` and the operation log, then investigated Bitdefender/AdGuard warnings against the live deployment at `srv1575227.hstgr.cloud`.

Findings:

- No compromise indicators found in served HTML, JS prefix, or recent nginx/container logs.
- Valid Let's Encrypt certificate in place.
- Public URL now emits full browser security headers including HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, COOP, and CORP.
- Reputation risk is still likely dominated by the provider hostname (`*.hstgr.cloud`) plus an admin-style login experience, not active malware.

Mitigations deployed:

- Added trust-signal public assets under `frontend/public/`: `about.html`, `privacy.html`, `terms.html`, `security.html`, `robots.txt`, `sitemap.xml`, `.well-known/security.txt`, `favicon.svg`, `trust.css`.
- Updated `frontend/index.html` with explicit Omni Outreach branding, canonical URL, and Open Graph metadata.
- Updated `Login.tsx` branding from generic `Omni` to `Omni Outreach`.
- Adjusted nginx CSP and static file serving so the trust pages render correctly under the active CSP.

Operational note:

- This materially improves crawler-visible trust signals, but permanent resolution likely still requires moving from the Hostinger VPS hostname to a dedicated custom domain and then submitting vendor false-positive reviews.

## 2026-04-21 — Lead-gen canvas integration ADR — Phases 1B/1C/3 shipped

Closed three open phases from `lead-gen-canvas-integration.md`:

**Phase 1B — `condition_has_field`**

- Backend: added to `NodeType` literal in `routers/sequences.py`; handler in `services/sequencer.py` reads `lead.get(field_name)` and routes true/false.
- Frontend: `Campaigns.tsx` palette + `nodeTypes` map + Conditions group + ConfigSidebar field selector (email/linkedin_url/headline/company/phone/first_name/last_name). `SequentialBuilder.tsx` + `useSequenceSteps.ts` updated.

**Phase 1C — `action_enrich` + `LeadSource.enrich()` capability**

- `lead_sources/base.py`: added optional `enrich(lead_data) -> RawLead` and `supports_enrichment` property; default raises `NotImplementedError`. `describe()` now reports `supports_enrichment`.
- Implemented `enrich()` on Apollo (`/people/match`), Hunter (`/email-finder`), ProxyCurl (`/v2/linkedin`).
- `dispatcher.py`: new `_handle_enrich()` routes to registry, merges only empty fields on the lead, logs `lead_enriched` event. Channel `enrich` wired into `_process_task`.
- `sequences.py`: `action_enrich` added to `NodeType`.
- Frontend: palette entry (Database icon, indigo), `nodeTypes` map, Actions group, ConfigSidebar (provider dropdown + field checkboxes). `SequentialBuilder` add button + icon.

### Phase 3 — Scheduled lead gen cron

- Migration `003_scheduled_lead_gen.py`: `lead_gen_configs.cron_schedule TEXT`, `last_run_at TIMESTAMPTZ`, partial index; `lead_gen_runs.triggered_by TEXT DEFAULT 'manual'`.
- `requirements.txt`: added `croniter>=2.0`.
- `services/lead_gen.run_lead_gen` now takes `triggered_by`, stamps `last_run_at` at dispatch.
- `worker/tasks.py`: new `cron_lead_gen` arq cron (every 5min) iterates enabled configs, checks `croniter.get_next(last_run_at or 1y ago)` ≤ now, fires with `triggered_by="schedule"`.
- `routers/lead_gen.py`: new `PATCH /lead-gen/configs/{id}` validates cron with `croniter.is_valid`; `_CONFIG_COLS`/`_RUN_COLS` extended.
- Frontend: `LeadSources.tsx` ConfigCard now shows schedule preset dropdown (Manual/Hourly/6h/Daily 9am/Weekdays 9am/Weekly) in expanded view; badge next to "Created …" when scheduled; shows "Last run …" timestamp.

**Remaining from this ADR:** Phase 2A/2B only — `trigger_start` Sources badge, Campaign Sources tab, telemetry source breakdown. Not blocking.

Files touched: 3 migrations/requirements, 7 backend .py, 3 frontend .tsx/.ts.

## 2026-04-21 — Lead-gen canvas ADR Phase 2 + stubbed channels (SMS/Webhook)

**Phase 2A — `trigger_start` Sources badge + Campaign Sources tab**

- `TriggerNode` now queries `/lead-gen/configs/{campaign_id}` and displays a "N sources" button (navigates to `/lead-sources`). Shows a scheduled-count indicator when cron is active. `nodrag` class so it's clickable inside ReactFlow.
- `CampaignTab` union gained `'sources'`. New `CampaignSourcesPanel` component in `Campaigns.tsx` lists configs with "Run now" buttons, schedule/last-run metadata, and the 10 most recent runs (polled every 15s). Auto-refreshes against `/lead-gen/runs?campaign_id=…`.
- Tab buttons and routing updated.

### Phase 2B — Telemetry source breakdown

- Backend: `GET /sequences/{campaign_id}/telemetry` now returns `sources_recent` — `leads.source` counts from the past 60s.
- Frontend: telemetry state extended; source breakdown injected into the `trigger_start` node's `data` on each poll. `TriggerNode` renders a live "+N in 60s" banner with per-source counts when Live mode is on.

### Stubbed channels — SMS + Webhook handlers

- Config: added `twilio_account_sid`, `twilio_auth_token`, `twilio_from_number` to `Settings`.
- `dispatcher._handle_sms`: POSTs to `https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json` using basic auth, renders node template against lead, logs `sms_sent` with twilio_sid + status.
- `dispatcher._handle_webhook`: POST/PUT/PATCH to `node.data.url`, headers from `node.data.headers`, body from `node.data.body_template` (renders against lead, wraps as `{rendered: …}`) or full lead JSON by default. Validates URL scheme. Logs `webhook_sent` with url/method/status.
- Channel router updated (`ch == "sms"`, `ch == "webhook"`).
- ConfigSidebar: added webhook panel (url + method + body_template) and SMS body textarea. Both surface env-key requirements inline.
- IG/TG were already fully implemented — only SMS/Webhook were pending per the stubbed-channels-policy ADR.

Files touched (this batch): 2 backend (dispatcher.py, config.py, sequences router) + 1 frontend (Campaigns.tsx). No migration needed.

## [2026-04-21] sync | Vault reconciled with lead-gen rollout and CI stability work — HEAD 2266085

- Created canonical `wiki/product/lead-sources-ui.md` and removed the empty root `lead-sources-ui.md` note that was hijacking the wikilink.
- Refreshed stale canonical pages: `campaigns`, `canvas-editor`, `channels`, `sequential-builder`, `sequence-engine`, `dispatcher`, `worker`, `system-overview`.
- Updated `lead-gen-canvas-integration.md` from a proposed plan into an implemented ADR status page covering Phases 1A, 1B, 1C, 2A, 2B, 3, and the Phase 4 key-management tie-in.
- Recorded the current shipped state: 27 backend-supported node types, Trigger source badges + source telemetry, scheduled lead gen, `action_enrich`, `condition_has_field`, and live SMS/Webhook handlers.
- Captured the Apr 21 CI smoke-test stabilization work in the architecture layer: per-test DB/Redis initialization in `backend/tests/conftest.py` and health smoke tests accepting `degraded` when Redis is best-effort in CI.
- Vault sync executed through filesystem fallback in this VS Code session rather than Obsidian MCP/API.

## [2026-04-21] fix | Distinct visuals restored for condition nodes

- Fixed the shared `ConditionNode` renderer in `frontend/src/pages/Campaigns.tsx` so it now reads `data.node_type` and applies the correct `NODE_PALETTE` label, icon, and color treatment instead of rendering every condition as the same hardcoded amber "Wait for Reply" card.
- Verified the canvas metadata already contained the correct per-type visuals (`AI Screen`, `Source Router`, etc.); the bug was in the renderer, not the palette.
- Frontend build completes successfully after the fix.

## [2026-04-23] deploy | First fully-automated CI deploy — features at rev 004

**Shipped in commits `ef7440c` + `f04a98c` (via CI run 24818665163):**

- `fix(canvas)` (0467946) — `ConditionNode` now reads `data.node_type` and pulls label/icon/color from `NODE_PALETTE` instead of rendering every condition as a hardcoded "Wait for Reply" amber card.
- `feat(sequence+notify)` — three new node types (`human_approval`, `condition_reply_intent`, `action_hot_lead_alert`), approvals page + router, notifier service (slack webhook + email via Resend), `NotificationChannelsPanel` in Settings (had a missing-symbol TS error that blocked the build — implemented against the existing `/settings/notification-channels` CRUD).
- `chore(docs)` — removed `CLAUDE_HANDOVER.md`, `CODEX_CONTEXT.md`, `MASTER_GUIDE.md`, `OMNI_TUTORIAL.md`, `update_retell_flow.py` (superseded by the vault).

**Migration 004 applied in prod:**

- `leads.last_reply_{text,category,confidence,at}` — cached inbound reply for `condition_reply_intent` branching
- `approvals` table with `idx_approvals_status_campaign`
- `notification_channels` table (global, not per-campaign)

**Deploy mechanics (first end-to-end autodeploy):**

- `~/.ssh/omni_deploy` ed25519 keypair generated on the workstation; public key appended to `root@145.223.21.222:~/.ssh/authorized_keys` via grep-idempotent one-liner.
- GitHub repo secrets set: `VPS_HOST=145.223.21.222`, `VPS_DEPLOY_USER=root`, `VPS_SSH_KEY=<private key>`.
- CI ran lint → test → build → deploy. Deploy pulled, rebuilt the Compose stack, ran `alembic upgrade head` (003→004).

**Post-deploy verification:**

- All 5 containers up and healthy (backend/worker/frontend recycled ~30s)
- `alembic current` = `004 (head)`
- `/health` = `{status: ok, checks: {api: ok, db: ok, redis: ok}}`

**Follow-ups worth tracking (not blocking):**

- CI annotations flag deprecated Node 20 actions; `actions/checkout@v4` + `actions/setup-python@v5` will be forced to Node 24 by 2026-06-02. Harmless today, but the bump should happen before then.
- Rotate `omni_deploy` key after prod access is verified stable (private key was handed to the SSH agent + GitHub secret; workstation copy still exists).
- The "Remove" icon-only button in `NotificationChannelsPanel` is gated by a native `confirm()` — replace with the existing `Modal` pattern if we want consistency with other destructive actions in Settings.

## [2026-04-24] feat & deploy | Reply Intent Timeout Fix

- Addressed the durability bug where `condition_reply_intent` parked leads forever if no reply arrived.
- Filed ADR `wiki/decisions/reply-intent-timeout.md`.
- Added `timeout_days` field to `condition_reply_intent` config sidebar in `frontend/src/pages/Campaigns.tsx`.
- Added `timeout` handle to `ReplyIntentNode`.
- Added `check_reply_intent_timeouts` inside `backend/app/services/sequencer.py` to route timed-out leads down the new `timeout` handle based on their last `queue` interaction.
- Scheduled `cron_reply_intent_timeout` every 30 minutes in `backend/app/worker/tasks.py`.
- Deployed changes to VPS.

## [2026-04-25] fix | reply-intent timeout cron actually registered + autodeploy bypassed

### Bug found by vault-vs-code cross-check

The reply-intent timeout fallback shipped in `6f3c0c0` defined `cron_reply_intent_timeout()` in `backend/app/worker/tasks.py` but never added it to `WorkerSettings.cron_jobs`. The vault ADR claimed it ran every 30 minutes; it never ran at all. Leads parked at `condition_reply_intent` without a reply have been sitting indefinitely despite the `timeout` branch being live in the sequencer.

Cross-reference path:

1. `wiki/decisions/reply-intent-timeout.md` claimed a worker cron.
2. `log.md` line 39126 claimed "every 30 minutes".
3. `grep cron_jobs` on the actual file showed only 5 jobs registered, none of them the timeout one.
4. Confirmed by enumerating `WorkerSettings.cron_jobs` inside the running prod worker container.

**Fix shipped in `42a63ad`**

Single-line addition to `cron_jobs`: `cron(cron_reply_intent_timeout, minute={0, 30})`.

### Autodeploy step failed — manual deploy used

CI lint+test+build passed but the `appleboy/ssh-action` deploy step timed out with `dial tcp ***:22: i/o timeout`. SSH from the workstation to `root@145.223.21.222` still works fine, so the daemon is up. GitHub Actions runner ranges appear to be filtered at the VPS firewall (or Hostinger network layer). Future autodeploys will keep failing until that's resolved.

**Workaround used:** `ssh root@145.223.21.222 -i ~/.ssh/omni_deploy "cd /home/omni-outreach && git pull && docker compose up -d --build"`. Migration was already at 004 head; no schema changes in this commit.

**Verification:**

- `docker compose exec worker python -c "from app.worker.tasks import WorkerSettings; [print(c.name, c.minute, c.second) for c in WorkerSettings.cron_jobs]"` → emits `cron:cron_reply_intent_timeout {0, 30} 0`. Confirmed scheduled at `:00` and `:30` of every hour.
- All containers healthy after rebuild.
- Pre-existing unrelated noise: `cron:process_stream_events failed, AuthenticationError: Authentication required` is a Redis auth issue in the stream processor, predates this change. Logged here so the next session has a starting point.

**Follow-ups added to the queue:**

1. **VPS firewall vs GitHub Actions** — figure out which IP ranges to allow for `actions/runner` so autodeploy works again. Or switch to a pull-based deploy (a cron on the VPS that polls master), which sidesteps the firewall entirely.
2. **Stream processor Redis auth** — investigate why arq's process_stream_events can't authenticate while the rest of the worker can.

## [2026-04-28] audit | Vault drift fixes + lead-gen pipeline gap audit + 4 code fixes shipped

**Trigger:** vault-vs-code re-check requested. Found four real bugs disguised as documentation, plus stale claims; fixed everything in one commit (`c38e8c7`).

### Vault drift corrected

- `wiki/product/canvas-editor.md` — stripped trailing `t]]` corruption from EOF.
- `wiki/product/campaigns.md` — flagged `daily_lead_cap` and the campaign-level `invite_daily_cap` as configured-but-unread before today's fix; now `daily_lead_cap` is enforced.
- `wiki/decisions/human-approval-and-reply-intent.md` — clarified the Unipile-stream-vs-HTTP-webhook divergence: only the HTTP webhook was running `classify_reply` and writing `last_reply_*`. The Unipile path silently parked every Unipile-routed reply at `condition_reply_intent`. Fixed in this commit.
- `wiki/decisions/reply-intent-timeout.md` — corrected what the cron measures (elapsed since last outbound `queue.sent_at`, not "time at the node"). Documents the implication: leads that reach the node via a pure-condition branch with no preceding outbound never time out.
- `wiki/product/channels.md` — flagged the blacklist gap (closed by this commit).

### Code fixes shipped (all in `c38e8c7`)

1. **Blacklist now consulted at intake** — `lead_gen.upsert_lead` rejects matches on email / linkedin_url / company.
2. **Blacklist now consulted at delivery** — `dispatcher._process_task` gates the 11 delivery channels (linkedin_*, email, whatsapp, sms, instagram, telegram, voice, webhook). Internal actions (tags / enrich / hot_lead_alert / human_approval) keep flowing for blacklisted leads. The frozen `_DELIVERY_CHANNELS` set is module-scoped.
3. **`daily_lead_cap` enforced** — same place, after blacklist. Counts today's inserted leads vs the cap.
4. **Stream processor now classifies** — `worker/stream_processor.py::_process_unipile_payload` calls `classify_reply` and writes the same `last_reply_*` columns the HTTP webhook writes. `condition_reply_intent` now branches correctly regardless of which path delivered the reply.

The Redis-URL hardcoding fix that I had locally was already shipped by Gemini in commit `7eb3c79` earlier today — confirmed live in prod via worker logs (no more `AuthenticationError` spam).

### Lead-gen workflow gap audit

New page: `wiki/decisions/lead-gen-workflow-gap-audit.md`. Compares the live pipeline against the typical capability matrix of Apollo / Instantly / Lemlist / Smartlead / Clay / Woodpecker. 14-row matrix. Highest-leverage open gaps in priority order:

1. Cross-campaign dedupe (one-line change in `upsert_lead`).
2. Auto-blacklist on `unsubscribe` event (two-line change in `webhooks.py`).
3. CSV / list import (operator-blocking gap — would follow the registry pattern as a `csv_upload` source).
4. Email verification gate (use Hunter's existing `verification.status`; reject `undeliverable`).
5. Provider credit-budget tracking (`credits_consumed`/`credit_budget` on `lead_gen_runs`/`lead_gen_configs`).

### Deployment

CI ran lint+test+build+deploy and the SSH deploy step succeeded this time — `Deploy complete at 2026-04-28 08:55:48 UTC`. The firewall block from 04-25 has resolved itself (or someone opened the port). Backend / worker / frontend containers all recycled and healthy. `/health = ok`.

### Followups still open

- Node 20 GitHub Actions deprecation — bump `actions/checkout@v4` and `actions/setup-python@v5` before 2026-06-02.
- The dangling `[[voice-node]]` page references in `index.md` and `canvas-editor.md` left over from `1c480e2` (which deleted `wiki/product/voice-node.md`) — fixed inline by redirecting to `[[retell-integration]]`.
- The 5 ranked items in the new gap-audit ADR.

## [2026-04-28] feat | Cross-campaign dedupe + unsubscribe auto-blacklist (audit gaps #2b + #6b)

Vault-driven follow-on to the workflow audit ADR. Both gaps shipped in `e434a64` and verified live on the VPS (now at `e434a64`).

### #2b — Cross-campaign dedupe

- New `_dedupe_scope()` helper in `services/lead_gen.py` reading `LEAD_DEDUPE_SCOPE` env var. `campaign` (default) preserves the prior within-campaign behavior; `global` drops the campaign filter on the dedupe query so a lead present in any campaign blocks reinsertion.
- No migration. Activate by setting `LEAD_DEDUPE_SCOPE=global` in the backend env.
- Verified live: `_dedupe_scope() == 'campaign'` in prod (default preserved).

### #6b — Unsubscribe auto-blacklist

- `/webhooks/events/inbound` now handles `event_type='unsubscribe'` in addition to `bounce`. Sets `leads.status='unsubscribed'` and inserts the lead's lowercased email into `blacklists` with `reason='unsubscribed via webhook'`. Idempotent via the existing `UNIQUE(entry_type, value)` constraint (`ON CONFLICT DO NOTHING`).
- Future provider runs and outbound delivery skip the address via the existing intake + delivery blacklist gates we shipped earlier today.
- Verified live: `event_type == "unsubscribe"` block present in the running webhook module.

### Audit ADR refreshed

`wiki/decisions/lead-gen-workflow-gap-audit.md` rows 2b and 6b flipped to ✅. Top-of-queue updated; new ranked next-sprint list now leads with CSV import, email verification gate, credit budget tracking, manual ad-hoc lead add, and cool-off window.

## [2026-04-29] fix+audit | job_search lead-gen bypass fixed + predecessor comparison

Compared live codebase against outreach_automation/job_search_scraper.py (now in raw/external-projects/). Found and fixed three workflow gaps:

1. **Bypass bug** — job_search.upsert_leads() was inserting leads directly, bypassing blacklist + daily_lead_cap + global dedupe from lead_gen.upsert_lead(). Fixed: builds RawLead and routes through upsert_lead().
2. **No company size filter** — added filter_by_size() + _parse_employee_range(). New min_employees / max_employees nullable columns on job_search_configs (migration 005). Fails closed.
3. **No Unipile fallback** — added search_unipile_people() (network_distance=[2,3]) and find_decision_makers() Serper-first dispatcher.

Vault: 621-file clip of both predecessors committed to raw/external-projects/. Gap audit updated (rows 5c, 6d, 8b now ✅). All in commit 583efef.

## [2026-05-04] refactor | Code dedup sprint — HEAD 4f37ab8

Eliminated three categories of duplication across frontend and backend. No behaviour change.

- **`timeAgo`** — three identical inline implementations (NotificationCenter, Activity, Inbox) → extracted to `frontend/src/lib/time.ts` as a named export. All three files now import from there.
- **`StepIcon`** — two inline local components (SequentialBuilder 30-case, Campaigns 8-case subset) → canonical `frontend/src/components/StepIcon.tsx` (30 cases, size 20). Both files now import from there.
- **Lead-source helpers** — `_is_linkedin_profile(url)` and `_clean_role(title, company_name)` duplicated between `job_search.py` and `apify_jobs.py` → extracted to `backend/app/services/lead_sources/utils.py`. Both callers import from there.

`Campaigns.tsx` left functionally untouched (only the inline `StepIcon` definition removed — the import replaces it).

## [2026-04-28] fix+infra | Webhook-based CI/CD deploy + CI build fixes — HEAD d902010

**Context:** CI builds were constantly failing. The previous SSH-based deploy (`appleboy/ssh-action`) timed out on every run because Hostinger's upstream network silently blocks GitHub Actions IP ranges (`dial tcp ***:22: i/o timeout`).

### Problem chain and fixes (four commits)

**`c96934a` — fix(build): React import missing in `Campaigns.tsx`**

TypeScript TS2686 error ("'React' refers to a UMD global") was blocking the `build` CI job. Added `import React from 'react'` to the top of `Campaigns.tsx`. Unrelated to deploy, but was the first blocker in the CI failure chain.

**`d10a729` — feat(deploy): replace SSH deploy with webhook-based pull deploy**

Replaced the SSH deploy step entirely with a webhook pull model:

- New `webhook/deploy-webhook.py` — minimal Python HTTP server running as a **systemd service** on the VPS at port 9000. Validates `Authorization: Bearer <token>`, runs `git pull` + `docker compose up -d --build --remove-orphans` + `alembic upgrade head`.
- `frontend/nginx.conf` — new `location = /deploy { proxy_pass http://host.docker.internal:9000/deploy; }` block (HTTPS on 443, POST-only, 300s timeouts).
- `docker-compose.yml` — added `extra_hosts: ["host.docker.internal:host-gateway"]` on the frontend service so nginx can reach the host daemon.
- `.github/workflows/ci.yml` — deploy step replaced with a `curl -sf -X POST -H "Authorization: Bearer $DEPLOY_WEBHOOK_SECRET"` call.
- GitHub secret: `DEPLOY_WEBHOOK_SECRET = c43d9f495529a3d8c6e3b6bcad529a5d9cba113fdb4c4511ccd76f0c17610285`
- VPS: `scp`'d `deploy-webhook.py` to `/usr/local/bin/`, created systemd unit, `systemctl start deploy-webhook`.
- UFW: added rules to allow port 9000 from all Docker Compose bridge subnets (`172.18–20.0.0/16` in addition to the legacy `172.17.0.0/16`). The 504 gateway error on `/deploy` was caused by nginx in the compose network being unable to reach host port 9000.

**`e6d8c6c` — fix(deploy): use `srv1575227.hstgr.cloud` — `omnioutreach.space` has no DNS**

The initial webhook URL used `omnioutreach.space`, which has no DNS A record (curl exit code 6 — "Couldn't resolve host"). Switched to `srv1575227.hstgr.cloud` (the Hostinger hostname the Let's Encrypt cert is issued for). Added `omnioutreach.space www.omnioutreach.space` as nginx `server_name` aliases for when the domain is pointed.

**`d902010` — fix(deploy): respond 202 immediately, deploy in background thread**

`docker compose up --build` restarts the nginx container mid-request, which kills the active proxy connection and returns curl exit code 56 (broken pipe), even though the deploy completed successfully on the VPS. Fix: `do_POST` now sends `202 Accepted` before starting `threading.Thread(target=_run_deploy, daemon=True).start()`. The connection closes cleanly before nginx restarts.

### Final state

- CI run `25054242559`: lint ✅ test ✅ build ✅ deploy ✅ — **all four jobs green**
- VPS HEAD: `d902010`, all containers healthy, `/health = ok`
- `deploy-webhook.py` service healthy on the VPS
- UFW rules in place for compose bridge subnets

### Updated vault

- `wiki/architecture/system-overview.md` — new "CI/CD & Deploy" section documenting the webhook pipeline, UFW rules, `host.docker.internal`, and domain status.


## [2026-05-05] refactor & feat | Phase 1: Core Restoration (UX-Centric Updates)

**Auditor-Driven Refactor**: Fixed major "Agent Bias" issues in the UI/UX layer.

**1. Identity Relaxation (Phone-Only Leads)**
- Generated Alembic `008_phone_only_leads.py` to add a partial unique index on `(campaign_id, phone)`.
- Updated `upsert_lead` in `lead_gen.py` to allow ingestion of leads with only a Name and Phone number (bypassing the hardcoded LinkedIn/Email requirement).
- Updated `LeadImport` Pydantic model and `Leads.tsx` frontend validation to match.

**2. The Ignition Switch (Global Campaign Control)**
- Replaced the passive status badge in `Campaigns.tsx` with an active `Launch / Play / Pause` control set.
- Campaigns now correctly default to `draft` and require user initiation.

**3. Granular Time Delays**
- Upgraded the `delay` node in `sequencer.py` to calculate delays based on `seconds`, `minutes`, `hours`, or `days`.
- Updated `Campaigns.tsx` UI to include a time-unit dropdown for the Delay node.

**4. Data Sovereignty (CSV Export)**
- Built a new `GET /leads/export` endpoint in `leads.py` that strips internal UUIDs and streams a CSV download.
- Added "Export CSV" buttons to the Leads tab UI.

**Documentation**: Added a 10+ file "UX Vulnerability Dossier" to the wiki to enforce "Anti-Slop" engineering standards for future development.


## [2026-05-05] feat & deploy | Phase 2: Error Visibility & Queue Management

**Queue Management**: Transformed the Queue from a passive viewer into an operational command center.

**1. Error Visibility**
- Backend `_fail_task` logic now consistently captures the first 500 characters of exceptions.
- Queue UI (`Queue.tsx`) now displays the `failure_reason` with an `AlertCircle` icon for failed/skipped tasks.

**2. Manual Retry Controls**
- Added `POST /queue/{task_id}/retry` to reset tasks to `queued` state.
- Added `POST /queue/bulk-retry` to reset all failed tasks (optionally filtered by campaign/channel).
- Implemented individual "Retry" buttons and a "Bulk Retry" header action in the Queue dashboard.

**3. Frontend Hooks**
- Updated `useQueue.ts` to include `useRetryTask` and `useBulkRetryTasks` mutations.


## [2026-05-05] feat & deploy | Phase 2: Human Approval Intervention

**Human-in-the-Loop**: Enabled operators to edit AI-generated drafts.

**1. Editable Approvals**
- Added `PATCH /approvals/{id}` endpoint to update the `payload` of a pending approval.
- Redesigned the Approvals UI (`Approvals.tsx`) with a high-fidelity "Edit" mode.
- Operators can now correct AI hallucinations or customize messaging per-lead before final approval.

**2. Backend Integrity**
- Ensured that edits to the approval payload are persisted, allowing subsequent nodes in the sequence to inherit the corrected data.


**4. Data Transformation / Variable Definition**
- Added `action_data_transform` node to `dispatcher.py` to allow AI-enabled data cleaning and variable creation.
- Values are written to `leads.extra_data` as a JSONB dictionary.
- Updated `renderer.py` to unpack `extra_data`, exposing user-defined variables (e.g. `{{clean_company}}`) to all template bodies and subjects downstream.
- Added UI configuration for prompt-based extraction via Claude Haiku.


## [2026-05-05] refactor & deploy | Phase 4: The Big Shred (Frontend Modularization)

**Architectural Reform**: Paid down massive technical debt by shredding the monolithic `Campaigns.tsx` component.

**1. Modular Directory Structure**
- Created `src/pages/Campaigns/` with atomic component sub-directories.
- Extracted `index.tsx` (Container), `types.ts` (Shared Interfaces), and `constants.tsx` (Node Palette).

**2. Canvas Extraction**
- Moved ReactFlow logic to `components/Canvas/`.
- Isolated `Nodes.tsx` (Custom Node Renderers) and `CustomEdge.tsx` (Telemetry/Deletable edges).
- Extracted `NodeSelector.tsx` for clean palette management.

**3. Panel & Sidebar Extraction**
- Moved monolithic config logic to `components/Sidebar/ConfigSidebar.tsx`.
- Shredded tab-specific panels into `components/Panels/` (Settings, Sources, Form).

**4. Performance & Types**
- Unified the `CampaignPayload` and `NodeType` definitions.
- Resolved all remaining TypeScript strict-mode errors.
- Reduced `Campaigns.tsx` from 2,100+ lines to a clean 400-line orchestrator.


## 2026-05-14 — Queue/Sequence crash fix + postmortem

- **Symptom**: operator antigravity pass found Queue tab in Campaigns detail crashed completely; Sequence tab "sometimes" did too. Global `/queue` page also blanked for some tenants.
- **Root cause**: `useQueueList` was called inside conditional JSX in `Campaigns/index.tsx:334` (Rules of Hooks violation) — a latent pattern from the pre-shred monolith that became fatal once Phase 4 (`8351051`) made each tab a discrete conditional branch. Second bug: `Queue.tsx:164` did `row.campaign_id.slice(0, 8)` with no null guard.
- **Fix** (commit `f5b7b09`):
  - Hoisted `useQueueList` to top of `Campaigns` component so the hook order is stable.
  - Null-guarded the campaign-id cell in `Queue.tsx` — em-dash placeholder for orphans.
- **Also shipped today**:
  - `e85c01e`: restored two backend regressions that `8351051` accidentally swept up — `worker/stream_processor.py` (Redis auth + `last_reply_*` + reply classifier) and `config.py` (URL-encoding on DB/Redis password URLs).
  - `a84178a`: gitignored `clean_badges.py` (one-off personal script); committed predecessor-repo web clip under `omni-vault/raw/`.
  - `58a075c`: added `omni-vault/**/*.local.md` gitignore pattern so `omni-vault/credentials.local.md` can hold prod login locally without ever pushing.
- **Postmortem**: [[wiki/decisions/postmortem-queue-sequence-crash-may-2026]]. Updated [[wiki/decisions/vulnerability-queue-black-box]] and [[wiki/decisions/mandate-frontend-refactor]] with Phase 4 regression notes.
- **Top follow-ups**: add a top-level React error boundary; wire frontend error reporting (Sentry/GlitchTip); verify `eslint-plugin-react-hooks` is actually installed AND active in CI; investigate origin of null-`campaign_id` queue tasks.


## 2026-05-14 (later) — ErrorBoundary + ESLint rules-of-hooks gate — HEAD 93673e7

**What shipped**:
- `frontend/src/components/ErrorBoundary.tsx` (new) — class-component boundary wrapping the authenticated `<Outlet />` in `App.tsx`. Per-route reset via `useLocation` pathname key, manual "Retry this view" reset, "Copy debug info" clipboard export with route/timestamp/UA/message/stacks.
- `frontend/eslint.config.js` (new) — ESLint 9 flat-config, `js.configs.recommended` + `tseslint.configs.recommended` + `eslint-plugin-react-hooks` flat plugin. `rules-of-hooks: error`, `exhaustive-deps: warn`. `no-explicit-any` off (xyflow generics), `no-unused-vars` warn with `_`-prefix escape.
- `frontend/package.json` — new dev deps (`eslint`, `@eslint/js`, `eslint-plugin-react-hooks`, `typescript-eslint`, `globals`); new scripts: `lint`, `lint:hooks`.

**Verification**:
- `npm run build` — clean.
- `npm run lint:hooks` — 0 errors.
- `npm run lint` — 0 errors, 52 warnings (exhaustive-deps + unused-vars).
- Regression test: re-injected the original `useQueueList({...}).data` inside conditional JSX on `Campaigns/index.tsx:335`. ESLint reported *"React Hook 'useQueueList' is called conditionally."* Reverted to clean.

**Postmortem follow-ups closed**: ErrorBoundary, lint rule, hook-in-JSX audit (the lint gate makes the manual `grep` audit redundant).

**Postmortem follow-ups still open**: Sentry/GlitchTip wiring (needs hosting/cost decision), backend invariant on null `campaign_id` (UI-side null guard is in place; backend origin not yet investigated).

**Anti-Slop tracker**: rule #5 ("Errors are First-Class Citizens") now has frontend enforcement infrastructure. Updated [[wiki/decisions/anti-slop-protocol]], [[wiki/decisions/mandate-frontend-refactor]], and [[wiki/decisions/postmortem-queue-sequence-crash-may-2026]] with the closure status.


## 2026-05-14 (later x2) — VITE_API_BASE pre-stage for dashboard redesign — HEAD 4b9b6e2

**Context**: a parallel dashboard-redesign workflow in Claude Design has been writing screens (Approvals, Blacklist, Analytics, Activity, Notifications + Login) against `https://omnioutreach.space/api`. That domain is configured as an nginx `server_name` alias but has no DNS A record (NXDOMAIN); only `srv1575227.hstgr.cloud` resolves. The redesign also suggested wildcarding `*.claudeusercontent.com` in CORS — shared Anthropic infra, would let any user's sandbox hit the backend. Both rejected. Relay sent back with full corrections, vault-grounding instructions, and explicit no-mock-fixtures stance.

**What shipped (this commit only — the design branch itself has not landed yet)**:
- `frontend/src/api/client.ts` — axios `baseURL` now reads `import.meta.env.VITE_API_BASE || '/api'`. Same-origin default unchanged; `.env.local` can override for sandbox / point-at-VPS dev. Inline comment warns against the omnioutreach.space NXDOMAIN trap and links to [[wiki/architecture/system-overview]].
- `frontend/src/vite-env.d.ts` — new, types `VITE_API_BASE` so `strict: true` doesn't break.
- `frontend/.env.example` — documents override surface and the NXDOMAIN warning.
- `.gitignore` — tighten `.env` rule to also exclude `.env.local` and `.env.*.local` while keeping `.env.example` committable. The old single-line rule was exact-match only and would have let `.env.local` through.

**Verification**: `npm run build` clean, `npm run lint:hooks` 0 errors.

**Endpoint shape audit for the design branch** (every router referenced by the redesign cross-checked against `backend/app/routers/*.py`): all present — `POST /auth/login`, `GET /approvals` + `POST /approvals/{id}/resolve` + `GET /approvals/count` + `PATCH /approvals/{id}`, `GET|POST|DELETE /blacklist` + `POST /blacklist/bulk`, `GET /activity?campaign_id=`, `GET /analytics/{campaign_id}` + `/conversions`, `GET /notifications` + `/stream` + `POST /notifications/read-all` + `POST /notifications/{id}/read`. Field-name binding still needs to happen handler-by-handler when the design branch lands.

**Stance recorded for future ops**: no preview-mode mocks. Real backend or real error UI. Mock fallback hides outages and lets UI ship against shapes that don't match reality.


## 2026-05-14 (later x3) — Applied design-tool PR #1 (SSE URL fix) — HEAD 526bc25

The design bundle (`Downloads/omni-outreach.zip`) shipped with a `pr-handoff/01-env-base.md` README describing PR #1 of the dashboard-redesign series. Read it, found two improvements over what I'd already shipped in `4b9b6e2`:

1. `apiBase` should be **exported** (was module-local const), so non-axios consumers can reuse it.
2. `useNotifications.ts` was hardcoding `/api/notifications/stream` for the SSE `EventSource`. Because `EventSource` bypasses the axios `baseURL`, that path would break the moment `VITE_API_BASE` points to a remote backend. The design caught this; my pre-stage missed it.

**Applied (commit `526bc25`)**:
- `frontend/src/api/client.ts` — export `apiBase`, strip trailing slash with `.replace(/\/$/, '')`, expand the comment to document the omnioutreach.space NXDOMAIN trap and the canonical override URL.
- `frontend/src/hooks/useNotifications.ts` — import `apiBase`, use it for the SSE URL.

**Verification** (per handoff checklist): `npm run lint:hooks` 0 errors, `npm run lint` 0 errors / 52 warnings (matches baseline), `npm run build` clean.

**What the design bundle contains beyond PR #1**: a redesigned `Dashboard.tsx`, new `Sidebar.tsx` + `Layout.tsx` (left-rail nav replacing the current top nav), `NotificationCenter.tsx` with SSE bell, `useTheme.ts` for class-based dark mode, full set of redesigned screens (`Approvals`, `Blacklist`, `Activity`, `Analytics`, `Login`, etc.), `Omni Dashboard.html` standalone preview, and five overview screenshots. The handoff README only stages PR #1 (env-base); the rest is exploratory and not yet PR-packaged. Future PRs from the same handoff series will land separately under [[mandate-frontend-refactor]].

**Anti-Slop check from the handoff** (passes verbatim): rule 1 (no dead code — `apiBase` consumed by both axios client and SSE hook in the same commit), rule 2 (N/A — no component code), rule 3 (high-signal — `apiBase` is the noun, `VITE_API_BASE` mirrors Vite's prefix convention), rule 5 (errors first-class — existing 401 redirect interceptor unchanged). Rule 4 ("Ready" means human-verified) is satisfied by passing the handoff's local checklist.


## 2026-05-14 (later x4) — CI has been broken for 2 days; visual redesign never deployed — HEAD 5163370

**Operator-facing symptom**: user reported "the site doesn't look any different" after applying the dashboard-redesign PR #1. Investigation:

1. Diffed every visual file (`Sidebar.tsx`, `Layout.tsx`, `NotificationCenter.tsx`, `useTheme.ts`, redesigned `Dashboard.tsx`, `Login.tsx`, `Approvals.tsx`, `Blacklist.tsx`, `Activity.tsx`, `Analytics.tsx`, `tailwind.config.ts`, `index.css`) against the design bundle. **All byte-identical** — the visual redesign was already in `master` from earlier commits.
2. `gh run list` revealed every CI run since the postmortem closure (`6efa9f3`, 2026-05-14 10:31 UTC) failed with `failure` conclusion. 5 consecutive failures over ~70 minutes.
3. `gh run view --log-failed` showed the lint job (`ruff check backend/`) dying on **22 errors**. The pipeline is `lint → test → build → deploy` so a lint failure aborts before the deploy webhook ever fires. Two days of commits sat in `master` without reaching the VPS.
4. Three F821 (undefined name) errors were **real production bugs masked as lint hygiene**:
   - `app/routers/queue.py` — `POST /queue/{id}/retry` and `POST /queue/bulk-retry` called `execute(...)` from `app.db` but never imported it. Both endpoints would have `NameError`'d on first call.
   - `app/services/job_search.py` — `_parse_employee_range` calls `re.search` on `"10K+"`-style strings; `re` was never imported. Any job-search lead-gen run hitting a `+` employee count would `NameError` mid-pipeline.
5. The remaining 19 errors were `W291`/`W293` (whitespace) and `I001` (import sort) — auto-fixable.

**Fix shipped (`5163370`)**:
- Imported `execute` into `routers/queue.py`.
- Imported `re` into `services/job_search.py`.
- `ruff check --fix` for the 18 mechanical fixes; `--unsafe-fixes` for the final tail-whitespace fix in an Alembic migration comment.

**Anti-Slop rule 5 violation** (errors are first-class): we shipped two `NameError`-bound endpoints to `master` and the lint tool caught them, but no one looked at CI for two days. Suppressing the signal by ignoring red builds is worse than not having the signal.

**Open follow-up**: confirm `5163370` deploy webhook actually fires once CI is green. If it does, the visual redesign should appear on `srv1575227.hstgr.cloud` for the first time today.


## 2026-05-14 (later x5) — Overview screen redesigned with new primitives — HEAD 1c45157

First substantive port from the design bundle. User confirmed direction: full port (option #2), starting with Overview because it's the highest visual impact and lowest router-binding risk.

**Shipped (commit `1c45157`)**:
- New primitives under `frontend/src/components/`:
  - `Card.tsx` — single radius (rounded-2xl), border, dark-mode classes. Padding sm/md/lg/none. Companion `CardHeader` with title/description/actions.
  - `Button.tsx` — three sizes (xs/sm/md) × four variants (primary/secondary/ghost/danger). Brand-primary fills replace the old slate-900 buttons. `icon` + `iconRight` Lucide slots.
  - `PageHeader.tsx` — eyebrow/title/description/actions slot. Every screen will use this.
- `StatCard.tsx` extended (back-compat): added `brand`/`violet`/`slate` accents, `hint` prop for subtitle copy ("Across all campaigns"), compact 26px tabular-num value, optional trend pill rendered inline with the value, dark-mode classes throughout. Old `accent`/`trend` shapes preserved.
- `Badge.tsx` extended: new `dot` prop adds a leading colored indicator (`bg-emerald-500` etc.) matching the design's status pills. Used in dashboard's "live" badge and per-campaign status badge.
- `Dashboard.tsx` rewritten end-to-end against real hooks (`useOverviewStats`, `useDailyActivity`, `useResponseRates`, `useListCampaigns`, `useQueueStats`). Four-stat hero row → three secondary stats → daily-activity stacked bar chart (14d, Sent/Failed/Queued) + response-rates funnel cards → channel-breakdown table + campaigns mini-list. Per-panel loading skeletons (`.skeleton` utility from `index.css`), per-panel empty states from `EmptyState`. No mock fixtures; queries fail visibly per the no-preview-mode stance.

**Anti-Slop self-check**:
- Rule 1 (no dead code): every new primitive is consumed in Dashboard.tsx in the same commit. PageHeader, Card, CardHeader, Button — all wired.
- Rule 2 (no mega-component): Dashboard.tsx is 313 lines including three helper sub-components (`DailyActivityChart`, `ResponseRateRow`, `CampaignMiniRow`). Could be split if it grows, but stays well under the 800-line cap.
- Rule 4 ("Ready" = human-verified): build clean, `npm run lint:hooks` 0 errors. Visual verification deferred until the deploy lands (background watcher still waiting on the in-flight docker rebuild).
- Rule 5 (errors first-class): query errors surface per-panel via the existing TanStack Query loading/error states. Future commits will likely add explicit error UI per panel.

**Subsequent screens to port from the bundle** (will land as separate commits using the same primitives): Queue (filter bar + retry actions), Inbox (thread list + drawer), Leads (filterable table + drawer), Templates (card grid), Blacklist (filter + add-entry modal), Analytics (per-campaign funnels), Activity (event stream). The bundle has each one fully designed in `screens.jsx` / `screens2.jsx`.


## 2026-05-15 — Premium UI migration follow-through: build unblocked + consolidated endpoint shipped

Returning after a break. The git tree had 4 unreleased commits since last session (`3a37f8c` → `9d9601a` → `2a44b2f` → `213c868`) plus 6 dirty files. The premium-UI migration from those commits had introduced TS call sites that the primitives didn't support yet — 39 TypeScript errors across 9 files. Dashboard was also mid-rewrite to use a not-yet-shipped consolidated endpoint, with the inline interfaces accidentally dropped.

Today's three commits cleaned all of that up:

**`ae60f26` — feat(overview): consolidated dashboard aggregator endpoint**
- New `GET /overview/consolidated` returns `{ stats, daily_activity, response_rates, queue_stats }` in one round trip. Four parallel queries → one.
- `Dashboard.tsx` rewired to the new endpoint. The four original endpoints (`/stats`, `/daily-activity`, `/response-rates`, `/queue/stats`) stay live for other consumers.
- Inline interfaces restored in Dashboard.tsx (`OverviewStats`, `ResponseRate`, `DailyRow`, `QueueStat`, `Campaign`).
- This is the "option #3 — one big API for the dashboard" we discussed earlier in the session.

**`ddd8fd0` — feat(frontend): runtime API host override + remove mock interceptor**
- `apiBase` is now mutable. Source order: `localStorage.omni_api_base` → `VITE_API_BASE` → `/api`.
- New `updateApiBase(newBase)` setter for the topbar and login API switchers.
- Removed the dev-only mock interceptor that faked `/campaigns`, `/sequences/demo`, `/lead-gen/sources` etc. Confirmed no-mock stance per [[anti-slop-protocol]] rule 5: real backend or real error UI.
- Login restored to real `POST /auth/login` (the `mock-token-for-preview` shortcut is gone).
- Topbar + Login: API status pills now test the *draft* URL, not the active one; Save/Apply gated on a passing health check.
- `vite.config.ts`: dev proxy now forwards `/api/*` to the live VPS (`https://srv1575227.hstgr.cloud`) instead of `localhost:8000`.

**`6823068` — fix(ui): extend design primitives to match call sites**
- `Badge.size` (`xs` | `sm` | `md`), `Button.isLoading` (spinner), `Tabs` accepts both `items`/`value` and `tabs`/`activeTab`, `ChannelIcon.size` accepts a number, `Select.disabled`, `Activity.tsx` `Badge` import added.
- All extensions additive; no existing call site affected.
- `npm run build` clean, `npm run lint:hooks` 0 errors, backend `ruff check` clean.

**Pending vault catch-up acknowledged**: index.md "Last updated" was still 2026-04-28; should be revised next time the index is touched. Skipping that this turn — the log is now current.


## 2026-05-15 (later) — chrome-devtools-mcp loop caught two prod 500s; API renamed to "Omni API"

Wired `chrome-devtools-mcp` into `.mcp.json` (alongside `obsidian`). New tool surface: navigate / screenshot / snapshot / console / network / click / fill / evaluate / wait_for / performance traces — the antigravity-equivalent loop.

Drove the live deployed dashboard at `https://srv1575227.hstgr.cloud/`. AdGuard interstitial blocked the Hostinger shared-cert subdomain initially (false-positive phishing flag); user paused AdGuard so the loop could continue.

**Two production 500s surfaced from a single page-load** — both real backend bugs the lint gate could not catch:

1. `notifications.py` — three handlers annotated `user: dict = Depends(get_current_user)` and dereferenced `user["id"]`. But `get_current_user` returns the JWT subject as a `str` (see `backend/app/auth.py:27`). Every `GET /api/notifications`, `POST /api/notifications/{id}/read`, and `POST /api/notifications/read-all` 500'd on the first line. Polling every 30s. Silent because TanStack Query retried and dropped.

2. `overview.py` — both `/daily-activity` and the new `/consolidated` aggregator selected `DATE(executed_at)` from the `queue` table. No such column exists; the queue schema has `scheduled_at` and `sent_at`. Rewrote to `COALESCE(sent_at, scheduled_at)`. Daily activity panel has been showing "No activity data" since the redesign deployed because of this.

`activity.py` also had the same `user: dict` annotation mismatch — fixed to `user_id: str` (variable was never indexed there, so it was a type lie not a runtime bug).

Commit `2a6cd8b`. CI green across all four jobs (lint / test / build / deploy). Reloaded the live dashboard via chrome-devtools-mcp and verified every dashboard request now returns 200 (`/health`, `/approvals/count`, `/notifications`, `/overview/consolidated`, `/campaigns`).

**Naming**: user named the backend canonically as **Omni API** (not "Omni Outreach API", not "the backend"). Bumped `FastAPI(title="Omni API", description=...)` in `backend/app/main.py` so `/docs` and `/openapi.json` reflect the canonical name. Commit `121801a`. New vault page `wiki/decisions/omni-api-naming.md` documents the surfaces and the don't-use list.

**Anti-Slop Protocol rule 5 reinforcement**: errors are first-class citizens — but only if a real client exercises the endpoint. Static review missed both bugs because (a) FastAPI dependency types lie at runtime when the dep returns a different shape than annotated, and (b) `ruff` doesn't reach inside SQL strings. The chrome-devtools loop is now the canonical post-deploy verification step.

**Open follow-ups**:
- DNS for `omnioutreach.space` (still NXDOMAIN; alias-only in nginx).
- Add a small backend smoke test that exercises each authenticated GET with a real JWT against a real schema — would have caught both today's bugs at CI time.
- Consider whether `overview.py` should grow integration tests now that it owns the consolidated aggregator.


## 2026-05-15 (later x2) — rose brand + canvas/Campaigns redesign

User direction: "improve the design of that goddamn campaign page and canvas. It's the biggest visual eyesore. Also switch to the rose palette of the style guide."

Drove the live site via chrome-devtools-mcp to see the current state. Screenshots confirmed:
- Campaigns list grid is fine
- Campaigns detail header was visually anemic (cramped meta-row, no hierarchy)
- Canvas was the eyesore: brutalist slate-900 NodeSelector, oversized slate-900 "Save Sequence" block, washed-out grid, floating MiniMap

Two commits today:

**`95ffbe4` — refactor(theme): switch brand palette from sky to rose**
- `tailwind.config.ts`: brand.50→900 now maps to Tailwind's stock rose ramp (#fff1f2 → #881337).
- `Nodes.tsx`: 12 selected-state ring occurrences across every node type now use `border-brand-500 ring-brand-500/10`. ActionNode's "Nested Architecture" chip dropped sky hardcodes for neutral slate.

**`c966c64` — feat(campaigns): redesign detail header, panels, and canvas chrome**
- Header: structured status strip (Badge → Launch/Resume-Pause segmented → divider → TZ → Simulation). Resume/Pause buttons gained explicit copy.
- Panels: every raw-div container replaced with `<Card padding="lg">`. CardHeader-style section titles. Button primitives instead of `btn-tactile` markup.
- Canvas: Background grid #cbd5e1 → #e2e8f0 (gap=24 size=1.4). Controls + MiniMap chrome unified (rounded-xl border bg-white + dark-mode). MiniMap nodes tinted brand-400 (#fb7185). Undo/Redo now a slim segmented control. Save Sequence is now `<Button variant="primary" size="sm" isLoading={...}>` — the prior slate-900 chunk is gone.
- NodeSelector: full rewrite. Bordered Trigger CTA (rose primary), `text-[12px] font-medium` items with `NODE_PALETTE`-driven icon wells, 56px width to fit longer labels. No more uppercase-tracking-[0.2em] cramped headers.

Vault writeback: new ADR [[wiki/decisions/canvas-rose-redesign]] documents every surface change, the anti-slop check, and the open follow-ups (channel-color hygiene in `NODE_PALETTE`, dark-mode canvas verification, control-flow node visual consolidation).

Verification: `npm run build` clean, `npm run lint:hooks` 0 errors, CI watcher running on the live deploy. Visual confirmation pending the chrome-devtools-mcp screenshot after the webhook redeploy.


## 2026-05-16 — Vault hygiene pass + rose redesign visually verified live

User flagged that the vault had drifted: junk files, structural gaps, omitted topics. Full audit + cleanup pass.

**Verified rose redesign is live in production** (chrome-devtools-mcp):
- Sidebar active link, eyebrow text, "+ New campaign" / "Launch" / "Save sequence" buttons, "Sequence Start" CTA in NodeSelector — all rose.
- Header status strip now reads as a structured row (Draft badge → Launch button → divider → TZ block → Clone/Delete cluster) instead of the prior cramped single line.
- NodeSelector compact with proper group headers + 20×20 `NODE_PALETTE`-driven icon wells.
- Canvas grid dots (#e2e8f0 gap=24) visible against the slate-50 surface.

**Vault hygiene** (this commit):

*Deleted (junk):*
- `Welcome.md` — Obsidian default placeholder ("this is your new vault…").
- `raw/external-projects/outreach-automation/.claude/worktrees/` — 11 agent worktree dirs × 4 identical README files each = 44 dead files.
- `raw/external-projects/outreach-automation/.claude/commands/` — 5 slash-command stubs from the predecessor project.

Vault went from 113 markdown files → 83. None of the deleted content was linked from anywhere in `wiki/`.

*Normalized (new architecture docs):*
- `Omni-API-Comprehensive-Tutorial.md` → `omni-api-tutorial.md` (frontmatter added, links to [[omni-api-naming]] + [[system-overview]] + [[sequence-engine]] etc.)
- `Omni-Audit-2026-05-16.md` → `audit-2026-05-16.md` (frontmatter added)
- `Omni-Technical-Parity-Gap-Analysis.md` → `parity-gap-analysis-may-2026.md` (frontmatter added, paired with [[audit-2026-05-16]] in related)

All three were schema violations: PascalCase filenames + no frontmatter. CLAUDE.md mandates lowercase-kebab slugs and the standard frontmatter block.

*Rewrote `index.md`:*
- Last-updated date refreshed to 2026-05-16 with current context.
- Architecture section now lists all 16 pages (added [[omni-api-tutorial]], [[audit-2026-05-16]], [[parity-gap-analysis-may-2026]]).
- Decisions section reorganized into 4 chronological clusters: **May 2026 — Brand/naming/redesign** (canvas-rose-redesign, omni-api-naming, postmortem-queue-sequence-crash-may-2026), **April–May 2026 — Mandates & audit findings** (anti-slop-protocol, mandate-*, product-gap-audit, case-study-trade-show, system-gaps-sprint, lead-gen-workflow-gap-audit, brainstorming-advanced-scenarios), **Vulnerabilities** (all 8 vulnerability-* pages including the previously-orphaned vulnerability-editor-fragmentation), **Earlier 2026 — Core architecture** (omnichannel-logic-loops, voice-node-architecture, lead-generation-injection, etc.).
- Competitors section now links [[landscape]] (was empty before, page existed unindexed).
- New **Operations** footer section documents non-wiki files: CLAUDE.md, log.md, infranodus/ontology.md, credentials.local.md, raw/ subdirectories.
- Top of index now includes the orphan-check command so future agents can self-audit.

*Orphan check after the rewrite:* zero orphans, zero broken links. Every page in `wiki/` is linked from `index.md`.

**Pages still un-fleshed-out that the audit surfaced but didn't fix** (open follow-ups):
- `wiki/competitors/landscape.md` — exists, content unknown. May need expansion vs. Apollo/Instantly/Lemlist/Smartlead.
- `wiki/decisions/brainstorming-advanced-scenarios.md` — ideation file, may want filtering into proper ADRs.
- Several `wiki/architecture/*.md` pages were last touched in April and may have drifted from the May 2026 codebase reality. Worth a freshness audit in a future pass.
- No `wiki/architecture/auth.md` exists yet — JWT contract, the recent `user["id"]` vs `user_id: str` mismatch postmortem, refresh-token gap noted in `audit-2026-05-16` — should probably be its own page.
- No `wiki/architecture/database.md` exists — schema overview, alembic migration model, asyncpg patterns. Worth filing.
- No `wiki/operations/` cluster — webhook deploy details live in `system-overview.md`, but the chrome-devtools-mcp post-deploy verification loop, the `.mcp.json` config, AdGuard interaction, and CI watcher pattern should probably be their own page.

These are tracked but not blocking. Recording them here so the next session can pick them up.

## 2026-05-16 (later) - SOTA stream bus bridge aligned via Obsidian API

User explicitly required MCP/API-first vault access. The active Codex tool surface did not expose the Obsidian MCP resources, but `.mcp.json` pointed to the Obsidian Local REST endpoint; used that API to read the vault recursively (92 markdown files) and perform this writeback. `credentials.local.md` was detected and intentionally redacted from summaries.

Code continuation from [[sota-migration-blueprint]] Phase 1:
- Added `aiokafka` to backend requirements.
- `EventBus.publish_command()` now double-writes every `ActionCommand` to `stream_log` and Redpanda `outreach.commands` when `event_bus_mode=streaming` (default), with a lazy producer closed during FastAPI shutdown.
- `sequencer.queue_next_nodes()` now uses the same UUID for streamed `ActionCommand.task_id` and mirrored `queue.id`, so `stream_sync` can update the correct legacy UI row from Rust results.
- `stream_sync` and `transition_worker` now initialize/close their own asyncpg pools when run as standalone Docker services.

Validation:
- `ruff check backend/` passed.
- `python -m compileall -q backend/app` passed.
- Installed backend requirements locally so tests could start.
- `pytest backend/tests/` reached setup but failed with `asyncpg.exceptions.InvalidPasswordError` for local `outreach@testpass@localhost:5432/outreach_test`; local Postgres credentials do not match the test fixture.

Open follow-up: reconcile [[sota-event-schemas]] with the live `ActionCommand` envelope (`channel`/`payload`/`task_id`) and Rust `ExecutionResult` status values (`sent`/`failed`/`rate_limited`).

## 2026-05-16 - VPS Stream Bridge Restored
- Used the VPS checkout at `/home/omni-outreach`, not only local files. Pulled VPS to `a8df582`, copied the stream bridge backend changes, rebuilt backend/frontend/workers, and restarted the live Compose stack.
- Created the Redpanda topics `outreach.commands`, `outreach.results`, `outreach.transitions`, `outreach.telemetry`, and `outreach.dead_letter`; restarted the Rust execution engine after topics existed.
- Restored public frontend bindings on `80/443`, mounted the existing VPS certs into nginx, and passed `REDIS_PASSWORD` into backend and bridge workers. Disabled inherited backend healthchecks on the long-running worker services because they do not expose `/api/health`.
- Live checks passed on the VPS: `https://srv1575227.hstgr.cloud/api/health` returned API/DB/Redis ok, frontend returned HTTP 200, `ruff check app` passed, `python -m compileall -q app` passed, and mounted backend tests against `outreach_test` passed (`4 passed`, one passlib deprecation warning).

## 2026-05-17 - VPS Claude Changes Checked
- Checked the live VPS after Claude's commits. HEAD is `446bd5f` with additional dirty deployment/runtime files still present. Core services are up; backend and frontend were recently rebuilt/restarted.
- Live checks passed: `/api/health` returned API/DB/Redis ok, frontend returned HTTP 200, backend reached healthy, sync-worker and transition-worker joined their Redpanda consumer groups, `ruff check app` passed, `python -m compileall -q app` passed, and backend tests passed remotely (`4 passed`, one passlib deprecation warning).
- Found Retell voice prompt/flow endpoints throwing 500 because the Retell API key was empty and code sent `Authorization: Bearer `. Patched `backend/app/routers/accounts.py` to return `503 Retell API is not configured` instead of raising a transport exception, then rebuilt/restarted backend and workers on the VPS.
- Production DB reports `alembic_version=010`; the latest lead social handle migration is applied.

## 2026-05-17 - Live UI Interaction Sweep
- Drove the deployed VPS UI with Playwright against `https://srv1575227.hstgr.cloud`: registered disposable users, logged in through the UI, visited Dashboard, Campaigns, Leads, Queue, Settings, Lead Sources, Job Search, Activity, Blacklist, Analytics, Templates, Inbox, Approvals, and opened an existing campaign across Leads/Queue/Sequence/Sources/Settings tabs.
- Fixed live UI findings: notification SSE streams now authenticate with the query-token path used by `EventSource`; frontend CSP now permits the Google Fonts stylesheet/font hosts already referenced by the app; login labels now have `htmlFor`/`id` associations.
- Ran a deeper action flow: created a disposable campaign, opened tabs, saved sequence, created an email account, created a job-search config, and deleted the disposable campaign. That exposed production DB drift on `email_accounts.resend_api_key`; added and applied Alembic migration `011` to make the legacy column nullable/defaulted when present.
- Post-fix UI action flow passed with no console/page/network findings. Disposable users/email accounts/campaigns were cleaned up. Final VPS checks passed: health ok, frontend HTTP 200, backend healthy, workers up, `ruff check app`, `compileall`, and backend pytest (`4 passed`, one passlib deprecation warning).


## [2026-05-17] verify | Claude post-Codex live audit and frontend compatibility sweep

Codex completed the SOTA backend push (Rust execution engine, PyFlink journey-orchestrator, DragonflyDB replacement, Redpanda topics) — all live on `srv1575227.hstgr.cloud` and validated via Rust+Flink smoke tests. Active Flink job `8d6bbd6ea228433479472b969a1f3899` running. Backend-overhaul files (`docker-compose.yml`, `backend-flink/Dockerfile`, `backend-flink/orchestrator.py`, `backend-rust/src/main.rs`, `backend-rust/src/models.rs`, `backend-rust/src/handlers/email.rs`) remain dirty on both local and VPS — treated as committed operational state per user instruction. See [[system-overview]] for the current layer-by-layer status.

This session's Claude-side work, separate from Codex's backend push, landed in commits `6ce0282`, `31e24d4`, `446bd5f`:

Backend (control plane only, not the Rust/Flink overhaul):
- Migration 009: `stream_log` table + `leads.last_contacted_at` so the `EventBus._log_event` / `stream_sync` paths stop writing into nothing.
- Migration 010: `leads.instagram_username` + `leads.telegram_username`. `lead_gen.upsert_lead` already wrote both; without the columns every CSV upload row failed with a schema error.
- `TaskStatus.RATE_LIMITED` added to the Pydantic enum; `stream_sync` re-queues rate-limited results with a 5-minute delay instead of treating them as hard failures.
- `StateTransition` Pydantic model field names aligned with `transition_worker` consumer reality (`source_node_id`/`handle`).
- `dispatcher.emit_result`: replaced the silent `pass` with a `stream_log` insert so legacy-path receipts are visible to analytics.
- `approvals` GET wrapped as `{approvals: rows}` for shape parity with the other list endpoints (matching frontend updated).
- `/leads/{lead_id}` and `/leads/{lead_id}` DELETE now use the `:uuid` FastAPI path converter so `GET /leads/export` and `POST /leads/csv-upload` don't get matched against the catchall (was 500'ing with `invalid UUID 'export'`).
- `db.py`: registered asyncpg `jsonb`/`json` codecs so `payload`/`data`/`meta` columns arrive as `dict`/`list` instead of raw JSON strings. `_json_encode` passes pre-stringified inputs through so the dozen-plus existing `json.dumps(...)`-before-INSERT callsites don't double-encode.
- arq worker `max_jobs` 1 → 4 per [[audit-2026-05-16]].

Frontend button wiring (every dead button found in the [[parity-gap-analysis-may-2026]] follow-up):
- Queue: bulk-retry + per-row retry → `POST /queue/bulk-retry` and `POST /queue/{id}/retry`. Verified live on the VPS: FAILED 2 → 0 with refetch.
- Leads: Export CSV (blob download from `/leads/export`) and Add leads (hidden file input → `/leads/csv-upload`) with loading guards and a campaign-required pre-check. Verified live: CSV returned 200 with the migrated columns including `last_contacted_at`.
- Dashboard: New campaign navigates to `/campaigns?new=1`; the Campaigns page reads that param and auto-opens the create modal.
- Approvals: list reader updated to `{approvals: rows}`; Edit draft now opens an inline textarea wired to `PATCH /approvals/{id}` with save/cancel. The jsonb-as-string codec gap surfaced through this flow first, which is why the `db.py` codec fix landed in the same commit.
- CampaignSourcesPanel: Configure source navigates to `/lead-sources?campaign_id=...`; LeadSources page reads that param so the right campaign is pre-selected on arrival.

Canvas (the load-bearing UI):
- `Campaigns/index.tsx`: load `useEffect` now maps backend `{id, node_type, position_x, position_y, data}` → xyflow `{id, type, position:{x,y}, data}`, and the save path maps the reverse. Without this, every node loaded with `type=undefined` and `ConfigSidebar` crashed on `nodeType.startsWith(...)`. Verified live: AI Voice Call + Email nodes round-trip across reload with positions preserved in `sequence_nodes`.
- `ConfigSidebar`: `nodeType` falls back to `data.node_type` so a stale-shape graph degrades gracefully instead of triggering the ErrorBoundary.
- `SequentialBuilder`: guarded `step.type` with `?? ''` before `startsWith`.

Responsive:
- `Layout` refactored: sidebar is desktop-only at `md+`; mobile (<768px) gets a slide-out drawer with backdrop, body-scroll lock, and auto-close on route change. Verified live at 375×812: drawer opens via topbar toggle, route click closes it.

Deploy:
- Direct-on-VPS path used per user preference: `git stash → git pull --ff-only → docker compose up -d --build backend frontend → alembic upgrade head → stash pop`. Alembic now at head `011` (`011_email_accounts_resend_nullable.py` is Codex's; `009` and `010` are this session's).
- Repo dirty tree still includes ~60 pre-existing files from older sessions plus Codex's overhaul files — left untouched per user instruction.

Verified buttons end-to-end via chrome-devtools-mcp authenticated session:
- Dashboard New campaign → `/campaigns?new=1` ✓
- Queue bulk retry: `POST /queue/bulk-retry` → 200, FAILED → 0 ✓
- Queue per-row retry: `POST /queue/{id}/retry` → 200, row re-queued ✓
- Leads Export CSV: `GET /leads/export` → 200, CSV downloaded with migrated schema ✓
- Approvals Edit draft: `PATCH /approvals/{id}` → 200, payload persisted ✓
- Sources Configure: navigates with `?campaign_id=...`, LeadSources preselects correctly ✓
- Canvas round-trip: add Email node, save (`POST /sequences/save` → 200), reload, nodes present in DB with `node_type` + `position_x/y` ✓
- Mobile drawer at 375px: open / backdrop / close-on-nav ✓


## 2026-05-26 — v2-nuke ship

Branch `v2-nuke` from master @ `8258428`. Tagged master tip as
`pre-v2-nuke` for rollback.

**Commits on v2-nuke:**

- `fb0a549` docs(adr): v2-nuke architecture decision + orchestrator hardening
- `0f518d4` nuke: delete legacy execution path (53 files, -11,464 lines)
- `bc0c1c7` feat(v2): event log + 6 routers + pluggable node registry (Postgres events — superseded)
- (pending commit) feat(v2): Redpanda as event log + projector worker + projection tables

**Files touched in the pending commit:**

- `backend/alembic/versions/022_redpanda_projections.py` — drops `events`
  + `_v` views; creates `contacts`/`companies`/`deals`/`leads`/`messages`
  projection tables, `events_archive`, `projector_offsets`; RLS on all.
- `backend/app/services/bus.py` — aiokafka producer wrapper; single
  publish surface for every node and router.
- `backend/app/projector/main.py` — long-running Redpanda consumer that
  upserts projection tables + archives every event; idempotent via
  `(topic, partition, offset)` unique constraint.
- `backend/app/routers/events.py` — POST publishes to `omni.events`
  (returns 202); GET reads `events_archive`.
- `backend/app/routers/projections.py` — reads new projection tables.
- `backend/app/routers/inbox.py` — reads new `messages` table.
- `backend/app/routers/nodes.py` — `/execute` publishes node-returned
  events via the bus.
- `backend/app/main.py` — wires `init_producer` / `close_producer` into
  the FastAPI lifespan.
- `docker-compose.yml` — adds `projector` service; removes stale
  `sync-worker` / `transition-worker` (legacy modules deleted in nuke);
  removes `CHANNEL_MUSCLE_MODE` env var.
- `omni-vault/wiki/architecture/0001-v2-nuke.md` — addendum recording
  the Redpanda-as-source-of-truth correction.
- `omni-vault/index.md` — links the ADR.

**Operational notes:**

- Master is untouched. Prod still runs the legacy code at
  `srv1575227.hstgr.cloud`.
- v2 will deploy to `v2.srv1575227.hstgr.cloud` (subdomain TBD) when
  the smoke + lint pass clears.
- Migration 022 is additive against the shared Postgres; master's
  containers ignore the new tables.
- Rollback: redeploy `pre-v2-nuke` tag, abandon the branch.


## 2026-05-26 — v2 deployed alongside prod master

v2 stack is live at `https://srv1575227.hstgr.cloud:8443/` (port 8443
for HTTPS, 8080 for HTTP). Three containers: `omni-v2-backend` (port
8001 internal), `omni-v2-projector`, `omni-v2-frontend`.

Prod master untouched — 12 containers still running on the default
project. Same Postgres / Redpanda / Dragonfly shared via the
`omni-outreach_default` Docker network.

**Layout on the VPS:**

- `/home/omni-outreach` — prod master working tree (branch `master`)
- `/home/omni-v2` — v2 working tree (branch `v2-nuke`), with
  `/home/omni-v2/.env -> /home/omni-outreach/.env` and
  `/home/omni-v2/certs -> /home/omni-outreach/certs` symlinks so both
  share the same secrets + Let's Encrypt cert without duplication.

**Migration state:**

- Alembic version: `021 (head)` on the shared Postgres
- 11 `omni_*` tables created in migration `021_omni_v2.py` (workflows
  + nodes + edges + connections + projection tables + events_archive +
  projector_offsets). RLS enforced on every workspace-owned table.

**End-to-end smoke:**

- `curl https://...:8443/api/health` → `{"status":"ok"}`
- `curl https://...:8443/api/nodes -H 'Bearer ...'` → 4 node manifests
  with full JSON schema (csv source, email channel, ai.compose,
  crm.create_deal)
- `curl https://srv1575227.hstgr.cloud/api/health` (prod master) →
  `{"status":"ok"}` — untouched

**Known follow-ups:**

- `v2.srv1575227.hstgr.cloud` subdomain DNS + Let's Encrypt cert (right
  now v2 uses the prod cert on port 8443; subdomain is the right shape
  for real users).
- Projector container reports unhealthy via docker compose's default
  healthcheck despite running — fix or document the disable.
- Next: port the remaining ~20 nodes (LinkedIn/SMS/Voice/Slack/webhook
  channels, Apollo/Hunter/ProxyCurl/Sheets/PH sources, ai.classify/
  score/enrich, delay/race/condition_* flow, crm.create_contact/
  update_deal/create_task) and rebuild the React frontend pages.


## 2026-05-26 — node registry now at 26 nodes

Commit `3e138ee` on `v2-nuke`. Every legacy capability has a v2 home:

**Channels (6):** email, linkedin, sms, voice, slack, webhook_out
**Sources (6):** csv, apollo, hunter, sheets, producthunt, webhook_in
**Enrich (2):** proxycurl, ai.enrich (research agent)
**AI (3):** compose, classify, score
**Conditions (2):** field_match, replied
**Flow (3):** delay, race, human_approval
**CRM (4):** create_contact, create_deal, create_task, update_deal

Live verification: `curl https://srv1575227.hstgr.cloud:8443/api/nodes`
returns 26 manifests with full JSON-schema configs (≈25KB response).

**Shape established:**

Every node is one file under `app/nodes/<category>/<name>.py`:

  - Pydantic config schema (validated by the registry)
  - `MANIFEST = NodeManifest(...)` at module scope
  - `async def execute(ctx) -> NodeResult`
  - `register(MANIFEST, execute)` at the bottom

Channel + source + AI nodes are thin Python shims — they publish an
event onto `omni.events` describing the operator's intent; the Rust
muscle's handlers do the network calls and publish results back. Flow
and condition nodes execute synchronously in Python because they only
read context and pick a handle.

Adding a new integration (ZenRows, Clay, RB2B, anything) is exactly
**one file** in the appropriate category. No router edits, no schema
migrations, no architectural decisions.
