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

