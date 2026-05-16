# Event Bus Architecture (Redpanda SOTA)

## 1. Overview
The Event Bus is the **Single Source of Truth** for the Omni SOTA stack. We have moved from database-polling to a durable, immutable event log.

---

## 2. Infrastructure
- **Technology**: **Redpanda** (Kafka-compatible).
- **Mode**: Exactly-once processing (idempotent producers).
- **Latency**: Sub-millisecond end-to-end.

---

## 3. Topic Hierarchy
| Topic | Format | Producer | Consumer |
| :--- | :--- | :--- | :--- |
| `outreach.commands` | JSON | Python Brain | Rust Muscle |
| `outreach.results` | JSON | Rust Muscle | Flink Lungs |
| `outreach.transitions`| JSON | Flink Lungs | Python Brain / UI |
| `outreach.telemetry` | JSON | All | DragonflyDB / Analytics |

---

## 4. The "Strangler" Logic
During the migration from Postgres to Redpanda:
1. **Double Write**: The Python `bus.py` writes to both Redpanda and the `stream_log` table.
2. **Topic Primary**: Workers are instructed to prioritize the Topic over the DB table.
3. **Recovery**: In the event of a Redpanda crash, the `stream_log` table can be used to re-seed the topics.

---

## 5. Security & Isolation
- **Encryption**: TLS 1.3 for all internal traffic.
- **SASL/SCRAM**: Each worker has its own credentials with scoped ACLs (e.g., Rust workers cannot write to `outreach.transitions`).
