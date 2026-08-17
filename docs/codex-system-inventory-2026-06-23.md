# OmniOutreach current system inventory

Status: onboarding truth pass in progress. This file records only claims verified against
the repository and, where stated, the live Contabo v2 box on 2026-06-23.

## Executive verdict

The v2 event-sourced system is real and running: the API, PostgreSQL, Dragonfly, Redpanda,
dispatcher, Rust muscle, Flink orchestrator, transition worker, projector, objective
worker, AI-jobs worker, and frontend are live. Production reported migration `040 (head)`,
one RUNNING Flink DAG-aware job, and a green `/api/health`.

The highest-risk finding is deployment drift. The production checkout is still at
`944be7c`, while the repository branch is at `db28139`, and the box contains more than
1,200 lines of uncommitted source changes plus untracked migrations/nodes. Current
containers were built at different times from this dirty tree. The deployed system cannot
be reproduced from the production checkout's Git commit.

## Verification results

- `python -m pytest ../audit/tests/ -q`: **189 passed**.
- Palette-node reachability contract: **passed**.
- `npx tsc --noEmit`: **passed**.
- Rust tests: **not run locally** because Cargo is unavailable in this environment.
- Live API health: `api`, `db`, `redis`, and `nodes` all `ok`.
- Live Alembic revision: `040 (head)`.
- Live Flink job: `Omni SOTA Orchestrator v0.2 (DAG-aware)`, state `RUNNING`, two tasks.

## API and frontend

### Works

- All 20 router modules are mounted in the FastAPI application
  (`backend/app/main.py:126` through `backend/app/main.py:157`).
- The backend exposes 100 decorator-defined endpoints across auth, workspaces, OAuth,
  events, projections, nodes, sources, canvas, integrations, inbox, AI Studio, approvals,
  suppression, templates, objectives, webhooks, tracking, and muscle-only internals.
- The active typed frontend client in `frontend/src/api/v2.ts` matches the principal
  authenticated UI routes, including workspace management, canvas CRUD/run, projections,
  inbox threads/replies, integrations/accounts, events, approvals, and AI jobs.
- Every page imported by `frontend/src/App.tsx:5` through `frontend/src/App.tsx:28` is
  routed at `frontend/src/App.tsx:44` through `frontend/src/App.tsx:81`.

### Dead/stale frontend seam

- The live `/campaigns` route imports `frontend/src/pages/Campaigns.tsx`
  (`frontend/src/App.tsx:15`), not the same-named directory index.
- `frontend/src/pages/Campaigns/index.tsx:16` imports the legacy campaign hooks and calls
  nonexistent `/campaigns` endpoints through `frontend/src/hooks/useCampaigns.ts:41`.
  This directory tree is not the routed campaign page.
- `frontend/src/hooks/useAnalytics.ts:23` calls nonexistent `/analytics/{campaignId}`.
- `frontend/src/hooks/useInbox.ts:26` and `:39` call obsolete `/inbox` and `/inbox/stats`;
  the real v2 API is `/inbox/threads...` (`backend/app/routers/inbox.py:87`).
- `frontend/src/hooks/useLeads.ts:66` through `:178` calls obsolete `/leads...` endpoints.
  `frontend/src/components/CsvImport.tsx:3` still imports one of these hooks, so that
  component must not be reintroduced without porting it to the v2 API.

Verdict: the routed UI uses the v2 client, but an unrouted legacy campaign subtree and
legacy hooks remain as misleading dead code.

## Execution spine

### Tenant isolation

`backend/app/db.py:165` refuses to acquire a tenant-scoped connection without a bound
workspace and sets transaction-local `app.workspace_id` before yielding the connection.
Background consumers must opt into `system_scope()`. Migration 021 enables and forces RLS
on every workspace-owned v2 table (`backend/alembic/versions/021_omni_v2.py:57`).

### Dispatch and credential boundary

`build_command` is called by the event dispatcher and inbox reply path. It renders the
channel payload and mints a one-shot credential reference instead of placing secrets on
Kafka (`backend/app/execution/commands.py:286`, `:333`). The Rust muscle redeems the
reference through the authenticated internal API (`backend/app/routers/internal.py:74`).

### Terminalization and fan-out

- `_terminalize_lead` uses a status-predicated UPDATE as the once-only terminal claim
  (`backend/app/execution/transition_worker.py:597` through `:631`).
- The claiming call notifies the parent barrier; redelivery rechecks release without
  recounting (`backend/app/execution/transition_worker.py:632` through `:688`).
- Fan-out barriers are pinned to their origin node and count failed children, preventing
  ghost releases and permanently waiting parents
  (`backend/app/execution/transition_worker.py:692` through `:717`).
- Root terminalization emits the durable `campaign.run.completed` fact for the separate
  objective worker rather than running the feedback loop inline
  (`backend/app/execution/transition_worker.py:643` through `:668`).

### Projector terminal stickiness

Generic lead events no longer fabricate `active`. Existing terminal rows preserve both
status and cleared current-node state
(`backend/app/projector/main.py:310` through `:351`). This directly protects the
SPINE-TERM-001 invariant.

### Pipeline metrics

Source results now emit `pipeline.metric` start/delta events
(`backend/app/execution/transition_worker.py:1603` onward). Production contains one
`omni_pipeline_metrics` row, proving the producer/projector path is no longer dead, though
one row is weak operational coverage.

## Rust muscle

`backend-rust/src/handlers/mod.rs:30` exhaustively dispatches the declared channel enum to
email, Unipile social channels, voice, SMS, webhook, tag mutation, enrichment, alerts,
transform/AI, HTTP, Apify, people/company discovery, Naukri, Indeed, and ATS handlers.
Unknown channels produce a structured failure. No `todo!` or `unimplemented!` stubs were
found under `backend-rust/src`.

There are 20 files in `backend-rust/src/handlers/`; several channel variants intentionally
share implementations (for example WhatsApp/Instagram/Telegram and the 12 ATS platforms).
Provider credentials are supplied by connection records or service configuration and
resolved through the credential-reference boundary.

## Live production reconciliation

Verified on the Contabo v2 box:

- 15 long-running v2/shared containers are up, including healthy backend, frontend,
  muscle, dispatcher, transitions, projector, objective, AI jobs, Flink, PostgreSQL,
  Dragonfly, Redpanda, Camoufox, and SearXNG.
- Database count: `0` leads with `status='active' AND current_node_id IS NULL`.
- Database count: `2,219` terminal leads.
- Database count: `1` pipeline metrics row.
- Database count: `0` configured `source.sheets` workflow nodes and `0` configured
  `source.producthunt` workflow nodes.

This confirms the migration-040 stranded-lead claim and confirms the metrics path has
written data. It does **not** prove Sheets or Product Hunt have completed a real live source
run; they are code-reachable but currently unused by saved workflows. Running a source
node would write production data and therefore still requires explicit approval.

### Critical Git/runtime drift

Production checkout:

- `HEAD`: `944be7c` (`feat(objective): stall watchdog — re-pursue frozen objectives`)
- tracked modifications: 21 source files, about 1,231 insertions / 221 deletions
- untracked source includes migration 040, `source.sheets`, `source.producthunt`,
  `fieldLabel.ts`, and Camoufox tests
- checked-out `origin/phase-out-non-v2` also points to `944be7c` because the server has not
  fetched/pulled the repository's current `db28139`

The modified files substantially overlap commits already present in the current local
branch, but the server tree has not yet been proven byte-for-byte equal to `db28139`.
Do not deploy, reset, clean, or pull until that reconciliation is reviewed and approved.

### Wrong-host warning

`193.203.161.15:/home/omni/marketing-automation` runs a separate legacy outreach system
under systemd and has no v2 OmniOutreach containers. Older notes or remembered commands
pointing there must not be used to verify or deploy this repository.

## Cleanup candidates (no deletion authorized)

- `frontend/src/pages/Campaigns/` legacy subtree.
- `frontend/src/hooks/useCampaigns.ts`.
- `frontend/src/hooks/useAnalytics.ts`.
- `frontend/src/hooks/useInbox.ts`.
- `frontend/src/hooks/useLeads.ts` and dependent `CsvImport.tsx`, after confirming no
  intended route/import remains.
- Stale wiki pages that still describe Hostinger, legacy compose coexistence, an absent
  Rust worker, or Flink as undeployed. Keep them only if explicitly marked historical.
- Root ignored screenshots and other scratch listed in `CODEX_ONBOARDING_PROMPT.md`, after
  a separate human-approved cleanup review.

## Remaining onboarding work

- Complete service-by-service caller verification.
- Complete node-by-node reachability classification and credential matrix.
- Read every Rust handler beyond dispatch/stub checks.
- Finish frontend component-level dead-code and functional-path review.
- Reconcile all 40 migrations with the actual production schema, not only Alembic head.
- Compare the dirty production tree byte-for-byte with `db28139` and identify unique
  box-only changes.
- Perform an approved dry source-node trace through Kafka, Flink, transitions, projector,
  and PostgreSQL.
