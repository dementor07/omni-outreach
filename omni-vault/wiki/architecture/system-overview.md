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
