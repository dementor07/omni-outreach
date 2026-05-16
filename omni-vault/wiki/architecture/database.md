---
title: Database (PostgreSQL · asyncpg · Alembic)
category: architecture
tags: [database, postgres, asyncpg, alembic, schema, migrations]
updated: 2026-05-16
related: [[system-overview]], [[omni-api-tutorial]], [[sequence-engine]], [[dispatcher]]
---

# Database

PostgreSQL 16. asyncpg pool. Alembic migrations. No ORM — raw parameterized SQL throughout the codebase. This page is the contract between the schema and every reader/writer.

## Pool

`backend/app/db.py`: Min 2, max 10 connections. No SSL (internal Docker network). Pool initialized on FastAPI `lifespan` startup, closed on shutdown.

## Tables (SOTA Grid)

### Core Logic (7)
| Table | Purpose |
|---|---|
| `users` | Email/password user accounts. |
| `campaigns` | Campaign container: name, status, timezone. |
| `leads` | Master lead row. Now a **Sink** for Flink state transitions. |
| `sequence_nodes` | Persisted graph nodes. |
| `sequence_edges` | Edges keyed by `source_handle`. |
| `stream_log` | **NEW.** The high-frequency event log for the bus. |
| `queue` | **LEGACY.** Mirror of the command topic for backward compatibility. |

### Execution & Delivery
| Table | Purpose |
|---|---|
| `linkedin_accounts` | Unipile-managed LinkedIn senders. |
| `email_accounts` | SMTP sender configs. |
| `voice_agents` | Retell agents. |

## The SOTA Architecture: Topics vs Tables
As of the 2026-05-16 refactor, we have moved to a **Log-Primary** architecture.

1. **The Topic is the Queue**: We no longer use `SELECT FOR UPDATE SKIP LOCKED` as our primary scaling mechanism. Redpanda topics (`outreach.commands`) are the definitive source for workers.
2. **Postgres is the Sink**: Database writes happen asynchronously. When a Rust worker finishes a task, it reports to the stream, and a Flink job "sinks" that result into Postgres for long-term history.
3. **Sub-ms Telemetry**: Live metrics (clicks/opens) bypass Postgres entirely and go straight to **DragonflyDB**.

## Schema: `stream_log`
Used for audit trails and stream-replay.
```sql
CREATE TABLE stream_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    event_type TEXT NOT NULL,
    payload JSONB NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
```

## Alembic Bookkeeping
Migrations are still the source of truth for schema changes.
- `001-008`: Core outreach and lead modeling.
- `009` (Planned): Migration to retire the legacy `queue` table once the Rust Muscle is at 100% parity.
