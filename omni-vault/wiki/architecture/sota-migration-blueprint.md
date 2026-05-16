# Omni SOTA Migration Blueprint (Final Consensus)

## 1. Executive Summary
This document outlines the final architectural design for Omni Outreach, transitioning to a **High-Performance Event-Driven Grid**.

### The "Brain & Muscle" Philosophy
*   **Brain (Python)**: Orchestration, AI Rendering, and Campaign Strategy. Optimized for Agility.
*   **Muscle (Rust)**: Execution, I/O, Networking, and Webhooks. Optimized for Performance and Reliability.
*   **Spine (Redpanda)**: The immutable event log connecting all services.

---

## 2. Target Architecture Stack
| Layer | Technology | Role |
| :--- | :--- | :--- |
| **Event Bus** | **Redpanda** | The central nervous system. Replaces DB-as-a-Queue. |
| **Execution Plane** | **Rust Workers** | Consumes commands, handles Unipile/SMTP/Proxies. |
| **Orchestration** | **Python (FastAPI)** | Manages the DAG traversal and AI content generation. |
| **State & Analytics** | **Apache Flink** | Managed state timers and real-time metric aggregation. |
| **Persistence** | **Postgres + Dragonfly**| Metadata (Postgres) and sub-ms Telemetry (DragonflyDB). |

---

## 3. The "Big Batch" Implementation Plan

### Phase 1: The Protocol Pivot (Immediate)
- [ ] **Omni Event Protocol**: Define strict Pydantic/Rust schemas for all stream data.
- [ ] **Stream Bus**: Implement the Python-side publisher to move tasks from DB to Redpanda.
- [ ] **Registry Pattern**: Refactor the Python Dispatcher to be a "Gateway" rather than a "Worker."

### Phase 2: Rust Execution Plane
- [ ] Implement the **Rust Ingestor** for webhooks (replacing FastAPI hooks for high-load).
- [ ] Implement the **Rust Outbound Worker** (replacing Python channel handlers).

### Phase 3: Flink Orchestration
- [ ] Move **Timers** and **Wait nodes** from Postgres to Flink.
- [ ] Implement **Real-time Analytics** sinks in Flink.

---

## 4. Why this is SOTA
1.  **Zero Polling**: Logic triggers instantly on events.
2.  **Stateless Execution**: Rust workers can be killed and restarted with zero data loss.
3.  **Horizontal Scale**: Each component (Python, Rust, Flink) scales independently.
4.  **Deterministic State**: Flink ensures a lead is always in one, and only one, node of the sequence.
