---
title: System Overview (SOTA)
category: architecture
tags: [backend, frontend, infra, streaming, rust, flink, redpanda]
updated: 2026-05-16
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

The blueprint above describes the target. As of the 2026-05-16 deploy on `srv1575227.hstgr.cloud`, this is what is live:

| Layer | State | Notes |
| --- | --- | --- |
| Frontend | Live | Rose brand; Campaigns/canvas redesign shipped 2026-05-15. |
| Backend (Omni API) | Live | FastAPI, asyncpg, alembic head `008`. Double-writes commands to `stream_log` + Redpanda. |
| Redpanda | Live | Topics `outreach.commands / results / transitions / telemetry / dead_letter` created on VPS. |
| Rust execution engine | **Not yet deployed** | Commands published but no Rust consumer attached on VPS. Legacy Python `dispatcher.run_once()` still does the work. |
| Flink journey orchestrator | **Not yet deployed** | `outreach.transitions` has no producer in prod — `transition_worker` is idle. |
| DragonflyDB | **Not yet deployed** | Telemetry overlay still reads from Postgres. |
| `sync-worker` | Live | Consumes `outreach.results` → updates `queue` + `leads`. Healthcheck disabled (no HTTP). |
| `transition-worker` | Live but idle | Consumer group is up; awaits Flink producer. |

Naming and brand:
- Backend is canonically the **Omni API** (`omni-api-naming` ADR).
- Brand palette is **rose** (`canvas-rose-redesign` ADR).
- Overview endpoint consolidated; frontend reads `VITE_API_BASE`.

The "SOTA" in this page's title refers to the target architecture. Today, the Python control plane still owns execution; the streaming spine is wired but the Rust muscle and Flink lungs are scaffolded, not running. See [[deploy-pipeline]] for the actual VPS topology and [[sota-event-schemas]] for the wire contracts.
