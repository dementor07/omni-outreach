---
title: Omni API Tutorial
category: architecture
tags: [api, backend, reference, tutorial]
updated: 2026-05-16
---

# Omni API Tutorial

The definitive technical guide for the [[omni-api-naming|Omni API]] (FastAPI + PostgreSQL + Redis). Structured as both reference and tutorial. Pairs with [[system-overview]] for the runtime / infra view and [[sequence-engine]] / [[dispatcher]] / [[worker]] for service-level deep-dives.

---

## 1. Core Architecture & Infrastructure

### 1.1 The Lifecycle of a Request
1. **Entry**: `main.py` initializes the FastAPI app, attaching global middleware (CORS, Request ID, Rate Limiting).
2. **Auth**: The `get_current_user` dependency (in `auth.py`) validates the JWT `Authorization: Bearer <token>` header.
3. **Database**: `db.py` manages a `Record` pool (via `asyncpg`). Queries use parameterized SQL (`$1, $2`) to prevent injection.
4. **Worker**: Background tasks (Lead Gen, Dispatching) are handled by **Arq** in `worker/tasks.py`.

### 1.2 Key Services
- **Sequencer (`sequencer.py`)**: The brain. Decides what happens next for a lead based on the Graph (Nodes/Edges).
- **Dispatcher (`dispatcher.py`)**: The hands. Executes the actual send (Unipile for LinkedIn, SMTP for Email, Retell for Voice).
- **Reply Classifier (`reply_classifier.py`)**: Heuristic regex engine for categorizing inbound messages.

---

## 2. API Module Reference

### 2.1 Authentication (`/auth`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/auth/register` | Create user account (Rate limit: 5/hr). |
| `POST` | `/auth/login` | Returns JWT access token (Rate limit: 10/min). |

### 2.2 Campaigns & Sequences (`/campaigns`, `/sequences`)
*Campaigns define the "container" and settings; Sequences define the "logic graph".*

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/campaigns` | List all campaigns. |
| `POST` | `/campaigns/{id}/clone` | **Tutorial**: Performs a deep-copy of the campaign, its settings, and the entire sequence graph (nodes + edges). |
| `GET` | `/sequences/{campaign_id}` | Fetch the React Flow graph. |
| `POST` | `/sequences/save` | Atomic update of the entire graph. |
| `GET` | `/sequences/{id}/telemetry` | **Real-time Stats**: Returns edge activity and node backpressure for the canvas overlay. |

### 2.3 Lead Management (`/leads`, `/lead-gen`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `POST` | `/leads/csv-upload` | Bulk intake with flexible header mapping (aliases for "LinkedIn URL", etc.). |
| `POST` | `/leads/bulk` | Perform actions (stop, move, tag) on multiple IDs. |
| `GET` | `/leads/{id}` | Returns lead profile + **Event Timeline** (every action taken on this lead). |
| `GET` | `/lead-gen/sources` | Lists active providers (Apollo, Apify) from the registry. |
| `POST` | `/lead-gen/trigger` | Manually starts a scraping run. |

### 2.4 Automation Chrome (`/queue`, `/approvals`, `/inbox`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/queue` | View scheduled actions. Statuses: `queued`, `locked`, `sent`, `failed`. |
| `POST` | `/queue/{id}/retry` | Resets a failed task to `queued`. |
| `POST` | `/approvals/{id}/resolve` | **Manual Gate**: Resumes a lead's flow after human review (Approve/Reject). |
| `GET` | `/inbox` | Aggregates all `reply` events across all channels (Email, LinkedIn, etc.). |

---

## 3. Webhooks & Data Ingress (`/webhooks`, `/track`)

### 3.1 Unipile (LinkedIn) Webhook
**Endpoint**: `POST /webhooks/unipile`
- **Security**: Mandatory HMAC SHA256 verification using `unipile_webhook_secret`.
- **Flow**: Incoming payloads are added to the Redis stream `omni_inbound_events` for near-instant processing.

### 3.2 Public Tracking
**Endpoints**: `/track/pixel/{id}.gif` and `/track/click/{id}`
- **Note**: These are **PUBLIC** endpoints. They use HMAC-signed URLs to prevent event forgery.
- **Action**: Recording an event (Open/Click) automatically triggers the `sequencer` to check for "Condition" nodes in the graph.

---

## 4. System Settings & Keys (`/settings`, `/accounts`)

### 4.1 Integration Vault
- **Encrypted at Rest**: API keys (Anthropic, Resend, etc.) are encrypted before storage.
- **Verification**: `POST /settings/integrations/{provider}/verify` makes a live test call to the provider to confirm the key works.

### 4.2 Account Management
- **LinkedIn**: Connected via Unipile IDs.
- **Voice**: Managed via Retell AI. The API proxies **Prompt** and **Conversation Flow** updates directly to Retell.

---

## 5. Tutorial: The "Life of a Lead"
1. **Intake**: A lead is added via `/leads/csv-upload` or a `/lead-gen` run.
2. **Start**: The `trigger_start` node in the sequence graph picks them up.
3. **Queue**: The `sequencer` creates a task in the `queue` table (e.g., "Send LinkedIn Invite").
4. **Dispatch**: The background worker picks up the `queued` task, locks it, and calls `dispatcher.py`.
5. **Event**: The lead accepts the invite. Unipile sends a webhook to `/webhooks/unipile`.
6. **Advance**: The `stream_processor` sees the "accepted" event and calls the `sequencer` to move the lead to the next node.
7. **Human Gate**: If the lead hits a `human_approval` node, they park until a user calls `/approvals/{id}/resolve`.
