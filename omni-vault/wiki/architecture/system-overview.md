---
title: System Overview
category: architecture
tags: [backend, frontend, infra, docker]
sources: []
updated: 2026-04-12
---

# System Overview

Omni is a multi-channel outreach automation SaaS evolving into a programmable outbound operating system. It sequences and sends messages across LinkedIn, WhatsApp, email, and voice — driven by a visual nodal canvas functioning as an Event-Driven State Machine.

## Core Abstractions

- **Lead**: A stateful entity traversing the graph.
- **Node**: A state transformer (Trigger, Action, Event/Listener, Condition, Control, Subflow).
- **Edge**: A transition rule defining logic paths.
- **Event**: A trigger for execution (e.g., webhook, timeout) that resumes parked leads.

## Stack

| Layer | Tech |
|-------|------|
| Frontend | React 18, TypeScript, Vite, Tailwind CSS, @xyflow/react |
| Backend | FastAPI, asyncpg, Python 3.11+ |
| Database | PostgreSQL 16 (Docker) |
| Queue | Redis 7 (Docker) |
| Infra | Docker Compose on VPS (145.223.21.222) |
| Branch | `outreach-threading` |

## Services (Docker Compose)

- `omni-outreach-frontend-1` — Vite build served via nginx, port 80
- `omni-outreach-backend-1` — FastAPI, port 8000
- `omni-outreach-worker-1` — background task worker
- `omni-outreach-db-1` — PostgreSQL 16, internal only
- `omni-outreach-redis-1` — Redis 7, internal only

## Key Directories

```
omni-outreach/
├── backend/app/
│   ├── routers/       ← FastAPI route handlers
│   ├── services/      ← business logic (sequencer, dispatcher, voice, etc.)
│   └── db.py          ← asyncpg query helpers
├── frontend/src/
│   ├── pages/         ← full-page React components
│   ├── components/    ← shared UI components
│   └── api/client.ts  ← axios instance with Bearer token interceptors
```

## Related Pages
- [[sequence-engine]] — how the nodal graph drives outreach
- [[channels]] — LinkedIn, WhatsApp, email, voice
- [[retell-integration]] — AI voice calls
- [[unipile-integration]] — LinkedIn + WhatsApp API
