---
title: SOTA Event Schemas
category: architecture
tags: [streaming, redpanda, contracts]
updated: 2026-05-17
---

# SOTA Event Schema Specification

Canonical wire contracts for the Redpanda topics that connect the Python control plane, Rust execution plane, Flink orchestrator, and Postgres bridge workers. Source of truth lives in `backend/app/core/events.py` (Pydantic v2 models). This page mirrors that file — if they diverge, the code wins and this page is wrong.

## 1. Topic Map

| Topic | Producer | Consumer(s) | Payload model |
| --- | --- | --- | --- |
| `outreach.commands` | Python `EventBus.publish_command` | Rust execution engine | `ActionCommand` |
| `outreach.results` | Rust execution engine | `stream_sync` (Postgres bridge), Flink | `ExecutionResult` |
| `outreach.transitions` | Flink journey orchestrator | `transition_worker` (re-enters Python sequencer) | `StateTransition` |
| `outreach.telemetry` | Rust + Flink | DragonflyDB sink, UI live overlay | `TelemetrySignal` (not yet typed) |
| `outreach.dead_letter` | Any worker on fatal failure | Operator inbox | Same as originating message + reason |

All topics created on the VPS as of 2026-05-16 deploy. See [[deploy-pipeline]] for topic-creation step.

---

## 2. `ActionCommand` (`outreach.commands`)

Defined in `backend/app/core/events.py`. Serialized via `command.model_dump_json()`; key is `command_id`.

```json
{
  "command_id": "uuid-v4",
  "task_id": "uuid-v4",
  "channel": "linkedin_invite | linkedin_dm | linkedin_inmail | linkedin_profile_view | email | whatsapp | instagram | telegram | voice | sms | webhook | add_tag | remove_tag | enrich | hot_lead_alert | data_transform",
  "lead": {
    "id": "uuid",
    "campaign_id": "uuid",
    "email": "string | null",
    "linkedin_url": "string | null",
    "first_name": "string | null",
    "last_name": "string | null",
    "company": "string | null",
    "chat_id": "string | null",
    "extra_data": {}
  },
  "payload": {},
  "metadata": {},
  "occurred_at": "iso-8601"
}
```

Notes:
- `task_id` is the legacy Postgres `queue.id` — Rust echoes it back in `ExecutionResult` so `stream_sync` can update the right row for UI parity.
- `channel` is the discriminator (not `task_type` — that name only appears in stale early drafts).
- `payload` is channel-specific (rendered body, subject, account credentials reference, etc.). Schemas per channel are not yet locked.

---

## 3. `ExecutionResult` (`outreach.results`)

```json
{
  "command_id": "uuid-v4",
  "status": "queued | locked | sent | simulated | failed | skipped | pending_approval",
  "error": "string | null",
  "is_retriable": true,
  "telemetry": {},
  "occurred_at": "iso-8601"
}
```

Consumer reality (`app/services/stream_sync.py`) currently branches on:
- `status == "sent"` → `UPDATE queue SET status='sent', sent_at=NOW()`, plus `leads.last_contacted_at`.
- `status == "failed"` → `UPDATE queue SET status='failed', failure_reason=error`.

The Rust worker is expected to additionally emit `status = "rate_limited"` for backoff signaling. That value is **not yet in `TaskStatus`** — it currently maps to `failed` with a retriable `error` until the enum is extended. Tracked as a follow-up.

Also note: stream_sync looks up `task_id` and `lead_id` on the result envelope directly, not nested. The Rust producer must flatten `task_id` and `lead_id` alongside `command_id` for the bridge to function. The Pydantic `ExecutionResult` model on the Python side does not enforce this — it is a Rust-side convention. Add to [[sota-rust-worker-protocol]] when locking the contract.

---

## 4. `StateTransition` (`outreach.transitions`)

```json
{
  "lead_id": "uuid",
  "campaign_id": "uuid",
  "from_node": "uuid | null",
  "to_node": "uuid",
  "event_type": "string",
  "metadata": {},
  "occurred_at": "iso-8601"
}
```

Consumer reality (`app/services/transition_worker.py`) reads `lead_id`, `source_node_id`, and `handle` from the envelope and calls `queue_next_nodes(lead_id, source_node_id, handle)`. **Field-name drift to flag**: the Pydantic model uses `from_node`/`to_node`; the consumer expects `source_node_id`/`handle`. Either Flink emits the consumer-shaped payload directly (bypassing the Pydantic model), or the model must be updated. This is the largest active contract gap.

---

## 5. `TelemetrySignal` (`outreach.telemetry`)

Not yet modeled in `events.py`. Tentative shape carried over from earlier draft:

```json
{
  "lead_id": "uuid",
  "campaign_id": "uuid",
  "signal": "opened | clicked | replied | bounced",
  "channel": "email | linkedin | ...",
  "weight": 1.0,
  "timestamp": "iso-8601",
  "meta": {}
}
```

Add a Pydantic model + this section becomes authoritative.

---

## 6. Open Contract Gaps (2026-05-17)

1. **`rate_limited` status** — Rust emits it; Python `TaskStatus` enum doesn't list it. Add the variant and a stream_sync branch.
2. **Transition envelope field names** — `from_node`/`to_node` (model) vs. `source_node_id`/`handle` (consumer). Pick one.
3. **`payload` per-channel schemas** — currently `dict[str, Any]`. Lock at least `email` and `linkedin_dm` shapes.
4. **`TelemetrySignal` Pydantic model** — promote from draft to typed.
5. **Dead-letter envelope** — no schema yet. Define `{ original_payload, topic, reason, occurred_at }` minimum.

See [[sota-rust-worker-protocol]] and [[sota-flink-state-machine]] for the corresponding consumer-side contracts.
