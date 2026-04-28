---
title: System Overview
category: architecture
tags: [backend, frontend, infra, docker]
sources: []
updated: 2026-04-28
---

# System Overview

Omni is a multi-channel outreach automation SaaS evolving into a programmable outbound operating system. It now covers both sides of the loop:

- **Lead intake** — provider-driven, optionally scheduled lead generation
- **Lead execution** — graph-based outreach across multiple channels

## Core Abstractions

- **Lead**: stateful record traversing the graph and carrying source/timeline metadata
- **Node**: trigger, action, condition, event/listener, or control module
- **Edge**: transition rule keyed by output handle
- **Event**: signal that resumes parked leads or enriches campaign telemetry

## Stack

| Layer | Tech |
|-------|------|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, @xyflow/react |
| Edge | nginx serving the SPA and proxying `/api/*` |
| Backend | FastAPI, asyncpg, Alembic, structured JSON logging |
| Database | PostgreSQL 16 |
| Queue / Streams | Redis 7 + arq |
| Infra | Docker Compose on VPS `145.223.21.222`, HTTPS via Let's Encrypt |

## Runtime Services

- `frontend` — built SPA plus trust-signal static pages behind nginx
- `backend` — FastAPI app, internal to the proxy network
- `worker` — background cron/queue/event processor
- `db` — PostgreSQL 16
- `redis` — authenticated Redis for queueing and streams

## Key Flows

### Lead Intake

- `routers/lead_gen.py` exposes provider registry metadata, config CRUD, trigger, and run history APIs.
- `services/lead_gen.py` dispatches provider searches, writes `lead_gen_runs`, updates `last_run_at`, and inserts deduplicated leads.
- `worker/tasks.py` runs `cron_lead_gen` every 5 minutes for scheduled configs.
- New leads immediately enter the graph through `sequencer.schedule_new_lead()`.

### Sequence Execution

- Campaigns render either the [[canvas-editor]] or [[sequential-builder]].
- Graphs save to `sequence_nodes` and `sequence_edges`.
- Queue rows are executed by the [[dispatcher]].
- Events, reply state, and telemetry resume parked leads and feed optimization.

### Delivery and Integrations

- Human-facing delivery channels are documented in [[channels]].
- Unipile powers LinkedIn, WhatsApp, Instagram, and Telegram.
- Retell powers voice calls.
- SMTP, Twilio, and generic webhooks fill the remaining delivery surface.

## Key Directories

```text
omni-outreach/
├── backend/app/
│   ├── routers/            FastAPI route handlers
│   ├── services/           sequencer, dispatcher, lead sources, integrations
│   ├── worker/             arq cron jobs and stream processor
│   └── db.py               asyncpg / Redis helpers
├── backend/tests/          pytest smoke fixtures and API checks
├── frontend/src/
│   ├── pages/              full-page React views
│   ├── components/         shared UI and builder primitives
│   ├── hooks/              data + graph hooks
│   └── api/client.ts       authenticated API client
└── omni-vault/             canonical project memory
```

## CI/CD & Deploy

### Pipeline (`.github/workflows/ci.yml`)

Four jobs run sequentially on every master push:

1. **lint** — `ruff check backend/`
2. **test** — pytest against ephemeral Postgres 16 + Redis 7 services; DB seeded from `schema.sql`
3. **build** — `docker build` for backend and frontend images
4. **deploy** — `curl -sf -X POST -H "Authorization: Bearer $DEPLOY_WEBHOOK_SECRET" https://srv1575227.hstgr.cloud/deploy`

Deploy only fires on master push when `DEPLOY_WEBHOOK_SECRET` is set in GitHub repo secrets.

### Webhook Deploy (`webhook/deploy-webhook.py`)

Replaced `appleboy/ssh-action` SSH deploy (which timed out because Hostinger's upstream blocks GitHub Actions IP ranges). New approach:

- `deploy-webhook.py` runs as a **systemd service** on the VPS at port 9000
- nginx in the frontend container proxies `POST /deploy` → `http://host.docker.internal:9000/deploy` (the `/deploy` location is restricted to POST and requires the Bearer token)
- CI `curl`s `https://srv1575227.hstgr.cloud/deploy` — HTTPS on 443, always open
- Webhook validates the token with `hmac.compare_digest`, responds **202 Accepted immediately**, then runs the deploy in a background thread:
  1. `git pull origin master`
  2. `docker compose up -d --build --remove-orphans`
  3. `docker compose exec -T backend alembic upgrade head`

The 202-before-deploy pattern is required because step 2 restarts the nginx container, which would kill the active proxy connection and return `curl` exit code 56 if the response hadn't already been sent.

### VPS Networking

- **UFW rules** — port 9000 explicitly allowed for all Docker Compose bridge subnets:
  - `172.17.0.0/16` (legacy docker0), `172.18.0.0/16`, `172.19.0.0/16`, `172.20.0.0/16`
- **`host.docker.internal`** — `extra_hosts: ["host.docker.internal:host-gateway"]` on the `frontend` service enables the nginx container to reach the host-level webhook daemon
- **Domain** — `srv1575227.hstgr.cloud` is the active HTTPS endpoint (Let's Encrypt cert). `omnioutreach.space` is configured as an nginx `server_name` alias but has no DNS A record yet.

### Quality Gate

The backend includes a lightweight pytest smoke suite covering health, auth, and unauthorized access checks. CI initializes the DB pool/Redis client in test fixtures, and `/health` is allowed to report `degraded` when Redis is only partially wired in the test environment.

## Related Pages

- [[sequence-engine]]
- [[dispatcher]]
- [[worker]]
- [[lead-sources-ui]]
- [[channels]]
- [[retell-integration]]
- [[unipile-integration]]
