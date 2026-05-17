# Worker Architecture (SOTA)

## 1. Overview
The Worker layer has evolved from a single Python background process into a **Polyglot Execution Plane**.

---

## 2. Worker Types

### A. The Python Worker (arq / cron)
- **Role**: High-level scheduled tasks and AI rendering.
- **Tasks**: `cron_lead_gen` (Intake), `render_ai_messages`.
- **Logic**: Sits in `backend/app/worker/`.

### B. The Rust Worker (Execution Engine)
- **Role**: High-throughput, low-latency I/O.
- **Topics**: Consumes from `outreach.commands`.
- **Channels**: Email (SMTP), LinkedIn (Unipile), Webhooks.
- **Performance**: Capable of handling thousands of concurrent outbound connections.

### C. The Flink Worker (Orchestrator)
- **Role**: Stateful journey management.
- **State**: Manages Lead ID keyed state and process timers.

---

## 3. Scaling Strategy
- **Python Workers**: Scale horizontally for AI heavy lifting.
- **Rust Workers**: Scale based on the **Lag** of the Redpanda command topic.
- **Flink TaskManagers**: Scale based on the volume of active lead journeys.

---

## 4. Error Handling & DLQ
Every worker follows the **Dead Letter Queue (DLQ)** pattern:
1. **Retriable Failure**: Re-publish to topic with backoff.
2. **Fatal Failure**: Publish to `outreach.dead_letter` for human intervention.
3. **Success**: Publish to `outreach.results`.


### D. Bridge Workers (Strangler)
- `app.services.stream_sync`: consumes `outreach.results` and mirrors Rust execution receipts back into Postgres `queue`/`leads` for UI parity. It initializes its own asyncpg pool when run as `python -m app.services.stream_sync`.
- `app.services.transition_worker`: consumes `outreach.transitions` and calls `queue_next_nodes()` so Flink timer events can re-enter the Python graph walker during the migration. It also initializes its own asyncpg pool as a standalone service.

These workers are the compatibility layer between the SOTA Redpanda/Flink/Rust path and the legacy Postgres-backed UI.

### 2026-05-16 VPS Worker Note
`sync-worker` and `transition-worker` are running as long-lived Compose services on the VPS. Their inherited backend HTTP healthcheck is disabled in Compose because these worker commands do not serve the backend health endpoint; readiness is verified from container logs and consumer group startup.
