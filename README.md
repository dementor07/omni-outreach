# OmniOutreach

A multi-tenant **CRM + outbound-automation + AI** platform — discover leads, run
multi-step / multi-channel outreach across a visual canvas, and let an AI loop pursue
campaign goals. Think HubSpot/Apollo, not a linear sequencer.

> **Status note (2026-06-23):** this README was rewritten to match the current
> **event-sourced "v2" architecture**. An earlier version described a legacy
> Sequencer/Dispatcher + ARQ/Redis design that was removed in the "v2-nuke" rebuild
> (migration `025` dropped the old schema). If anything below disagrees with the running
> system, **the running system wins** — re-verify on the box and update this file.
> Architecture decision records live in `omni-vault/wiki/architecture/` (start with
> `0001-v2-nuke.md`).

---

## 1. Architecture — the execution spine

The product is built on an **event-sourced state machine**. A canvas node never acts
directly; it emits an intent event, and a chain of workers carries the lead through its
journey. Every state change is an event (durable, replayable, audited).

```text
canvas node fires
  → intent event on omni.events            (Kafka / Redpanda)
  → dispatcher        builds an ActionCommand
  → outreach.commands
  → Rust "muscle"     does the real network I/O (send / discover / enrich)
  → outreach.results
  → Flink orchestrator turns a result into the next transition
  → outreach.transitions
  → transition_worker advances / fans out / terminalizes the lead
  → projector         writes the read-model projection tables
  → Postgres
```

**Why this shape:** the safety-critical logic (terminalization, fan-out/join barriers,
exactly-once sends, retries) lives in claim-gated, idempotent workers so Kafka's
at-least-once delivery and Flink's at-least-once sink can't double-act. Multi-tenancy is
enforced by **Postgres row-level security** (each query runs under the
`app.workspace_id` GUC), not just app-layer `WHERE` clauses.

### The workers (each is a compose service / container)

| Service (`docker-compose.v2.yml`) | Container | Entrypoint | Role |
|---|---|---|---|
| `backend-v2` | `omni-v2-backend` | FastAPI | REST API + canvas + auth |
| `dispatcher-v2` | `omni-v2-dispatcher` | `app.execution.dispatcher` | intent → ActionCommand |
| `muscle-v2` | `omni-v2-muscle` | Rust `execution-engine` | the real network I/O |
| `orchestrator-v2` | `omni-v2-orchestrator` | Flink job (`orchestrator.py`) | results → transitions |
| `transitions-v2` | `omni-v2-transitions` | `app.execution.transition_worker` | advance / fan-out / terminalize |
| `projector-v2` | `omni-v2-projector` | `app.projector.main` | events → projection tables |
| `objective-v2` | `omni-v2-objective` | `app.execution.objective_worker` | goal-pursuit feedback loop |
| `ai-jobs-v2` | `omni-v2-ai-jobs` | `app.execution.ai_jobs_worker` | ad-hoc AI scoring/compose jobs |
| `camoufox-v2` | `omni-v2-camoufox` | headless browser svc | anti-detect scraping for some sources |
| `frontend-v2` | `omni-v2-frontend` | nginx + built React | the dashboard + `/api` reverse proxy |

Kafka topics: `omni.events`, `outreach.commands`, `outreach.results`, `outreach.transitions`.

---

## 2. Tech stack

- **Backend:** Python 3.13, FastAPI, asyncpg. Workers are plain `python -m` processes.
- **Muscle:** Rust (`backend-rust/`) — ~19 handlers, one per `ChannelType` dispatch arm.
- **Streaming:** Redpanda (Kafka API) + Apache Flink (the orchestrator job).
- **Database:** PostgreSQL with row-level security; schema via Alembic (`backend/alembic/`).
- **Frontend:** React 18 + Vite + TypeScript, React Flow (`@xyflow/react`) for the canvas,
  TanStack Query for server state.
- **Integrations:** Unipile (LinkedIn/WhatsApp/IG/Telegram send + profile), Serper / SearXNG
  (discovery), ATS job boards (Greenhouse, Ashby, Lever, …), Apify, Anthropic (AI),
  Retell (voice), Google Sheets + Product Hunt (OAuth sources).

---

## 3. Nodes (the canvas building blocks)

Nodes live in `backend/app/nodes/`, auto-discovered at import. Categories:

- **`sources/`** — discover leads (web search, ATS boards, Naukri/Indeed, CSV, Google
  Sheets, Product Hunt, …). Either muscle-routed (emit a `source.*.requested` intent) or
  in-process (emit `contact.created` directly, like `source.csv` / `source.sheets`).
- **`channels/`** — outbound sends (email, linkedin, sms, voice, whatsapp, instagram,
  telegram, slack, webhook_out). Muscle-routed.
- **`ai/`** — enrich, compose, ICP screening. Muscle-routed (Anthropic).
- **`crm/`** — create/update contacts, companies, deals, tags, alerts. In-process.
- **`conditions/`**, **`flow/`** — branching, delays, business-hours windows, fan-out
  (`for_each`), join barriers, race, goal/end. Resolved in-process by the spine.

**Reachability invariant:** every side-effecting node must be reachable (a muscle
`ChannelType` arm, or in-process). The test
`audit/tests/test_contract_routing.py::test_every_palette_node_is_reachable` enforces this.
See `docs/adding-nodes.md` to add one.

---

## 4. Data model (read side)

Projections are written by the projector; the event log is the source of truth. Key tables:

- **CRM:** `omni_contacts`, `omni_companies` (+ `omni_company_aliases`, `omni_people_cache`),
  `omni_deals`.
- **Pipeline:** `omni_leads` (a lead's position + status in a workflow), `omni_messages`,
  `omni_tasks`, `omni_approvals`, `omni_lead_scores`, `omni_email_tracking`,
  `omni_pipeline_metrics`.
- **Canvas:** `omni_workflows`, `omni_workflow_nodes`, `omni_workflow_edges`.
- **Send infra:** `omni_connections` (encrypted credentials), `omni_sending_accounts`
  (per-seat rate caps + send windows), `omni_campaign_sending_accounts` (pool).
- **Event log / ops:** `omni_events_archive`, `omni_projector_offsets`, plus exactly-once
  ledgers (`processed_commands`, `omni_send_count_claims`).

Identity/tenancy tables (`users`, `workspaces`, `workspace_members`) are workspace-agnostic
and RLS-exempt by design. **The live DB is the schema source of truth** — reconcile against
`alembic current` on the box, not against any doc.

---

## 5. Local development

```bash
# Backend tests (source-faithful regression invariants in audit/tests/)
cd backend
PYTHONPATH=. DB_PASSWORD=testpass SECRET_KEY=test-secret-key-not-for-production \
  REDIS_PASSWORD="" python -m pytest ../audit/tests/ -q

# Frontend type-check / dev server
cd frontend
npm install
npx tsc --noEmit
npm run dev          # Vite dev server; proxies /api to the live backend (see vite.config.ts)
```

`audit/findings.json` is a running engineering ledger (issues found / fixed, with
evidence). Read it for history; re-verify any "FIXED" claim against the live system before
trusting it.

---

## 6. Deployment (read this before you deploy)

The stack runs on a Linux VPS via Docker Compose
(`docker compose -p omni-v2 -f docker-compose.v2.yml …`). **It is a live, multi-tenant
production system — every deploy/migration/destructive action needs explicit human
authorization, and no real outbound should be sent during testing.**

Hard-won facts about this box's deploy model:

- **App code is baked into images — there is no bind-mount.** Editing a file on the box's
  disk does nothing until you `build` that service's image and recreate the container:
  `docker compose -p omni-v2 -f docker-compose.v2.yml build <svc> && … up -d <svc>`.
- **`backend-v2`, `projector-v2`, and `transitions-v2` each build their OWN image** from
  `./backend/Dockerfile`. Rebuild the service that *runs the changed file* — rebuilding
  `backend-v2` does **not** update the transition worker.
- **Rust changes** require rebuilding `muscle-v2` (`cargo build --release` runs in the image
  build).
- **Migrations:** bake the new migration into the image, run `alembic upgrade head` from a
  one-off container off the fresh image, then recreate the long-running backend (so its own
  `alembic current` can resolve the new revision).
- **Stale-IP 502:** recreating `backend-v2` gives it a new container IP; the frontend's nginx
  caches the old one, so `/api` 502s until you `docker restart omni-v2-frontend`. Don't
  panic — check `127.0.0.1:8001` first.
- The public app is reached via a hostname (a security product may block the raw IP); a local
  Vite dev proxy is the friction-free browser-verify path.

> Server address, SSH key, and credentials are intentionally **not** committed here. The
> VPS IP and deploy cycle in older docs are out of date — get the current values from the
> operator / `omni-vault/`.

---

## 7. Repository layout

```text
backend/         Python: API, spine (execution/), projector/, nodes/, services/, alembic/
backend-rust/    The Rust "muscle" — network I/O handlers
backend-flink/   The Flink orchestrator job
frontend/        React + Vite dashboard
audit/           findings.json ledger + source-faithful regression tests
docs/            adding-nodes.md, event-streaming-and-postgres.md
omni-vault/      Obsidian wiki — ADRs + architecture maps (the durable design record)
nginx/, certs/, searxng/, services/, webhook/   infra + supporting services
docker-compose.v2.yml   the live stack (the root docker-compose.yml is legacy — verify)
```
