# OmniOutreach — Multi-Channel Outreach Control Plane

Multi-channel outreach automation platform (LinkedIn, WhatsApp, Email, AI Voice). This repository contains the FastAPI asynchronous backend, the React TypeScript frontend, and the Directed Acyclic Graph (DAG) execution engine.

## System Architecture

### Outreach Engine (DAG)
The platform has transitioned from a linear sequence model to a Directed Acyclic Graph (DAG) model. This allows for complex branching logic based on lead behavior (e.g., "If replied on LinkedIn, stop email follow-up; else, send WhatsApp message").

- **Sequencer (`backend/app/services/sequencer.py`)**: A graph traversal engine that identifies outgoing edges from a completed node and schedules the next task in the `queue`.
- **Dispatcher (`backend/app/services/dispatcher.py`)**: A worker loop that batch-locks queued tasks using `FOR UPDATE SKIP LOCKED` and executes channel-specific handlers.
- **Webhook Handler (`backend/app/routers/webhooks.py`)**: Listens for Unipile `message.received` events to update lead state and trigger conditional graph branches.

### Backend Stack
- **Framework**: FastAPI (Python 3.12)
- **Database**: PostgreSQL (via `asyncpg` for non-blocking I/O)
- **Worker**: ARQ (Redis-backed) for scheduled task dispatching
- **Integrations**: Unipile (Unified Messaging), Retell AI (Voice), Native SMTP (Email)

### Frontend Stack
- **Core**: React 18 + TypeScript + Vite
- **Canvas**: `@xyflow/react` (React Flow) for the nodal flow builder
- **State**: TanStack React Query + Zustand
- **Styling**: Pure Tailwind CSS + Lucide icons (No external UI libraries)

---

## Data Model (PostgreSQL)

### Table: campaigns
Stores global campaign constraints, timezone settings, and the builder mode preference.
- `sequence_mode`: `sequential` (linear list builder) or `canvas` (nodal graph editor).

### Table: sequence_nodes
Replaces the old `sequence_steps` table.
- `node_type`: `trigger_start`, `action_linkedin_dm`, `action_whatsapp`, `action_email`, `condition_replied`, `delay`.
- `data`: JSONB column storing node-specific configuration (e.g., `delay_days`, `template_id`).
- `position_x`, `position_y`: UI coordinates for the canvas.

### Table: sequence_edges
Defines directed connections between nodes.
- `source_handle`: Used for branching logic (e.g., `true` handle for "Replied", `false` for "Silent").

### Table: leads
Tracks the current state of a prospect within a sequence.
- `current_node_id`: FK to `sequence_nodes` acting as an execution bookmark.
- `replied_at`: Populated via webhooks to satisfy `condition_replied` nodes.

---

## Implementation Status

### Core Features
- **Dual-Mode Builder**: Users can build sequences via a high-speed linear list (Sequential mode) or an advanced graph editor (Canvas mode). The frontend "compiles" linear lists into graph nodes and edges automatically.
- **Unified Messaging**: Support for LinkedIn, WhatsApp, IG, and Telegram via Unipile unified `/api/v1/chats` endpoint.
- **Native Email**: High-deliverability SMTP implementation (bypass Unipile for email).
- **AI Voice**: Retell AI integration for automated telecalling.

---

## Deployment Context

### Infrastructure
- **Environment**: Containerized via Docker Compose.
- **Reverse Proxy**: Nginx (handling API proxying and frontend serving).
- **VPS Deployment**: `145.223.21.222` (default path: `/home/omni-outreach`).

### Local Development
**1. Backend**
```bash
python -m uvicorn app.main:app --reload --port 8000
```

**2. Frontend**
```bash
npm install
npm run dev
```

---

## Technical Documentation
For line-by-line analysis of the sequencer logic and builder compilation, refer to:
- `OMNI_TUTORIAL.md` — Architectural deep-dive and code tutorial.
- `CLAUDE_HANDOVER.md` — Engineering summary for next-step logic implementation (Nested Voice Flows).
