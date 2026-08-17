---
title: Backend Map
category: architecture
tags: [backend, python, rust, flink, index, event-sourcing]
updated: 2026-06-08
---

# Backend Map

Per-file index of the backend, from a full line-by-line read (2026-06-08): entire Python control plane, the Rust muscle spine + all handler behaviors, and the Flink orchestrator. Intent + role per file — repo is source of truth; query the [[codebase-memory-mcp]] graph for callers. Related: [[system-overview]], [[canvas-contract]], [[leads-pipeline]], [[frontend-map]], [[0001-v2-nuke]].

## The execution loop (one pass)

`source/channel node.execute()` emits a `<type>.queued|.requested` intent → **dispatcher** (`execution/dispatcher.py`) resolves channel via `commands.NODE_CHANNEL` + mints a credential_ref → publishes ActionCommand to `outreach.commands` → **Rust muscle** (`main.rs`) dedupes (processed_commands ledger) → `handlers::dispatch` → provider call → ExecutionResult to `outreach.results` → **Flink orchestrator** (`backend-flink/orchestrator.py`) keyed-by-lead timer → transition to `outreach.transitions` → **transition_worker** advances the lead down the matching edge. Conditions/flow nodes resolve locally (no muscle hop) via a synthetic result. The **projector** (`projector/main.py`) consumes `omni.events` and materialises all projection tables.

## Control plane — routers (`app/routers/`, mounted in main.py)

| Router | Prefix | Role |
|---|---|---|
| `auth` / `auth_google` | /auth, /auth/google | JWT (sub+ws), register/login (rate-limited), Google sign-in. `get_current_workspace` binds the RLS ContextVar. |
| `workspaces` | /workspaces | Workspace CRUD, members, invites, switch — multi-tenant team mgmt. |
| `oauth` / `oauth_producthunt` | /oauth/* | Google Drive/Calendar + ProductHunt OAuth (token store in `services/oauth_tokens`). |
| `internal` | /internal | The muscle's ONLY control-plane contract: one-shot credential-ref redeem/release, Bearer MUSCLE_SHARED_SECRET, constant-time compare, short-TTL multi-read. |
| `events` | /events | POST publish (allowlisted user-publishable types only) + GET historical log (omni_events_archive, prefix-match). |
| `projections` | /projections | Read side: contacts/companies/deals/leads(+columns)/. Leads joins contacts + dynamic columns — see [[leads-pipeline]]. |
| `nodes` | /nodes | Manifest registry surface; `/nodes/{type}/execute` ad-hoc. |
| `canvas` | /canvas | Workflow+node+edge CRUD, bulk graph save, **POST /run** (the trigger). |
| `integrations` | /integrations | `omni_connections` CRUD — one shape per provider; credentials encrypted at rest. The connection-check source for [[canvas-contract]] Refactor C. |
| `inbox` | /inbox | Thread list + history from omni_messages. |
| `ai_studio` | /ai | Lead scores + AI job log; POST /ai/jobs publishes `ai.<kind>.queued`. |
| `approvals` | /approvals | Resume half of park/resume: emits approval.resolved + a transition to un-park. |

## Execution (`app/execution/`)

- `dispatcher.py` — intent event → ActionCommand. `_is_intent` = suffix `.queued`/`.requested` ONLY (non-intent events are silently dropped — the CONTRACT-002 tag/alert bug history). `commands.py` — `NODE_CHANNEL` (node_type→ChannelType), `build_command`, credential minting. `transition_worker.py` — advances leads, `_fan_out` (the only lead-creating path besides POST /run), join barrier, KG resolve hook, retry/`__retry__`. `lead_columns.py` — workflow-scoped display columns (see [[leads-pipeline]]).

## Nodes (`app/nodes/` — 41, auto-discovered)

Two construction patterns: direct `MANIFEST = NodeManifest(...)` (40 nodes) and the `http_node`/`http_source_node` factory (`http_node.py`, used by `source.serper`). Categories: SOURCE (csv, webhook_in, serper, serper_people, linkedin_jobs, naukri), CHANNEL (email/sms/voice/whatsapp/instagram/telegram/linkedin/slack/webhook_out — thin shims emitting `channel.x.queued`), AI (compose, enrich, screen_company [fail-open], screen_person [fail-closed]), CRM (create_contact[+lead.contact_attached], create_deal, update_deal, create_task, add/remove_tag, hot_lead_alert, resolve_company), CONDITION (has_tag, field_match, replied, verify_person, company_filter), FLOW (delay, end, goal, join, race, split, wait_until, human_approval[park], for_each). Array config fields (Refactor B targets): `ai.enrich.fields`, `company_filter.{blocklist,reject_keywords}`, `linkedin_jobs.keywords`, `serper_people.titles`, `race.winner_event_types` (list[str]); `split.weights`, `wait_until.days_of_week` (list[int]).

## Services + core

- `db.py` — asyncpg pool + RLS tenant model: `SET LOCAL app.workspace_id` per txn, `system_scope()` bypass, `acquire()` fails loud without a tenant. `bus.py` — Redpanda producer + crash-tolerant `consume_forever` (poison-batch skip + dead-letter + commit-after-success). `encryption.py` — Fernet via HKDF-SHA256(SECRET_KEY) + legacy-SHA256 decrypt fallback (MultiFernet) — why rotating SECRET_KEY orphans creds. `config.py` — env Settings, rejects placeholder secrets, execution_mode/channel_muscle_mode. `company_kg.py` — resolver (exact→alias→fuzzy→create) + `cache_person` STUB (never called) + signal scoring. `people_scoring.py` — pure verification/lead-score functions. `core/events.py` — ChannelType enum (must stay in sync with Rust models.rs + NODE_CHANNEL). `tools/trace.py` — CLI run-reconstruction by correlation_id.

## The muscle (`backend-rust/src/`)

- `main.rs` — consume outreach.commands → processed_commands ledger dedupe → `handlers::dispatch` → outreach.results; at-least-once, 60min poll interval (Apify), dead-letters schema/serialize errors. `models.rs` — wire types; `ChannelType` has `#[serde(other)] Unknown` so an unknown channel deserializes to a clean error (not a parse crash). `handlers/mod.rs` — dispatch match (one arm per ChannelType; the 4th edit-point for a new muscle channel: Python enum + NODE_CHANNEL + Rust enum + this arm + handler). `credentials.rs` — redeem opaque ref via MUSCLE_SHARED_SECRET, in-memory only, release after. `common.rs` — `ok/fail/skipped/rate_limited` builders + the SSRF guard (`validate_outbound_url` resolves DNS, blocks loopback/RFC-1918/link-local/IMDS/CGNAT). `http_call.rs` — generic declarative-REST handler backing `http_node`. Handlers all follow redeem→call→common::ok, returning results in `lead_mutations` (tags, enrich fields, source company/people lists). `unipile.rs` = LinkedIn+WhatsApp+IG+Telegram (shared X-API-KEY shape). `proxy.rs` — per-lead proxy. `http.rs` — shared client pools.

## Orchestrator (`backend-flink/orchestrator.py`)

Keyed-by-lead PyFlink state machine on outreach.results → timers → transitions. sent/simulated→delay timer→next_handle; failed+retriable→5min `__retry__` bounded by MAX_RETRIES=3 then on_error; failed→on_error; skipped→immediate next_handle. `analytics.sql` — Flink SQL analytics sink.
