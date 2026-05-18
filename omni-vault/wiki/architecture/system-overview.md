---
title: System Overview (SOTA)
category: architecture
tags: [backend, frontend, infra, streaming, rust, flink, redpanda]
updated: 2026-05-17
---

# System Overview (Omni SOTA)

Omni is a **Stateful Stream Processing Grid** for multi-channel outreach. It has transitioned from a legacy Postgres-polling architecture to a high-performance, event-driven infrastructure designed for massive scale.

## 1. Architectural Philosophy: The "Brain & Muscle" Split
We decouple the **Intelligence** of the system from the **Execution** of the system.

- **The Brain (Python)**: Handles AI Rendering, Campaign Strategy, and the Control Plane.
- **The Muscle (Rust)**: Handles high-concurrency Network I/O, Webhooks, and Proxies.
- **The Spine (Redpanda)**: The immutable event log connecting Brain and Muscle.
- **The Lungs (Flink)**: The stateful memory for lead journeys and real-time analytics.

---

## 2. The SOTA Stack

| Layer | Technology | Role |
| :--- | :--- | :--- |
| **Frontend** | React 18, @xyflow/react | The Command Center. |
| **Control Plane** | **Python (FastAPI)** | The Logic and AI engine. |
| **Execution Plane**| **Rust (Tokio)** | High-speed outbound delivery. |
| **Stream Bus** | **Redpanda** | Durable event distribution. |
| **Orchestration** | **Apache Flink** | Lead state and timers. |
| **Memory** | **DragonflyDB** | Sub-ms telemetry and state cache. |
| **Persistence** | **PostgreSQL 16** | Relational metadata and analytical sink. |

---

## 3. Core Service Map

- `frontend`: React SPA for campaign building and mission control.
- `backend`: Python Control Plane. Emits `ActionCommand` events to Redpanda.
- `execution-engine`: Rust Muscle. Consumes commands and executes I/O (Unipile, SMTP).
- `journey-orchestrator`: Flink Lungs. Manages lead position in the DAG and timing.
- `redpanda`: The single source of truth for all system events.

---

## 4. Key Data Flows

### Outreach Execution
1. **Sequencer (Python)**: Publishes `ActionCommand` to `outreach.commands`.
2. **Worker (Rust)**: Picks up command, executes I/O via **Proxy**, and publishes `ExecutionResult`.
3. **Orchestrator (Flink)**: Receives result, updates **Managed State**, and registers a **Timer** for the next node.
4. **Analytics (Flink)**: Aggregates results and sinks metrics to **DragonflyDB** for the UI.

### Webhook Ingestion
1. **Ingestor (Rust)**: Receives high-load webhooks (LinkedIn/Email) and slams them into Redpanda.
2. **Brain (Python)**: Consumes filtered webhooks for AI sentiment analysis.

---

## 5. Related Specifications
- [[sota-migration-blueprint]]
- [[sota-brain-muscle-boundary]]
- [[sota-event-schemas]]
- [[sota-rust-worker-protocol]]
- [[sota-flink-state-machine]]
- [[dispatcher]] (Legacy Reference)
- [[sequence-engine]] (Legacy Reference)


---

## 6. 2026-05-17 Status — What's actually running on the VPS

The blueprint above is now deployed as the live backend spine on `srv1575227.hstgr.cloud`:

| Layer | State | Notes |
| --- | --- | --- |
| Frontend | Live | Rose brand; Campaigns/canvas redesign shipped 2026-05-15. |
| Backend (Omni API) | Live | FastAPI, asyncpg, migrations through resend-nullability hotfix. Emits command events to Redpanda. |
| Redpanda | Live | Topics `outreach.commands / results / transitions / telemetry / dead_letter` verified on VPS. |
| Rust execution engine | Live | Consumes `outreach.commands`, disables auto-commit, publishes `ExecutionResult`, sends schema failures to `outreach.dead_letter`. |
| Flink journey orchestrator | Live | PyFlink job `8d6bbd6ea228433479472b969a1f3899` running in the Flink session cluster; emits timer transitions to `outreach.transitions`. |
| DragonflyDB | Live | Replaced Redis container image while keeping service name `redis` for app compatibility; healthcheck passes. |
| `sync-worker` | Live | Consumes `outreach.results` → updates `queue` + `leads`. Healthcheck disabled (no HTTP). |
| `transition-worker` | Live | Consumer group is up and listening for Flink transition events. |

Naming and brand:
- Backend is canonically the **Omni API** (`omni-api-naming` ADR).
- Brand palette is **rose** (`canvas-rose-redesign` ADR).
- Overview endpoint consolidated; frontend reads `VITE_API_BASE`.

Validation on 2026-05-17:
- Public and direct health checks return `api/db/redis = ok`.
- Rust smoke command flowed `outreach.commands` -> `execution-engine` -> `outreach.results` with metadata preserved.
- Flink smoke result flowed `outreach.results` -> timer -> `outreach.transitions` with `event_type: transition`.
- Backend `ruff check app`, `compileall`, and pytest suite pass on the VPS.

Historical failed/canceled Flink jobs may remain visible in the session-cluster history from the deployment smoke tests; the only active orchestrator job at handoff is running.
