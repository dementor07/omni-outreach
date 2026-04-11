# Omni-Outreach: Technical Handover & Architectural State

This document summarizes the transition from a linear outreach model to a unified, multi-channel nodal flow (DAG) system.

## 1. Current State (Commit: `6b1de81`)
The codebase has been refactored to support a Directed Acyclic Graph (DAG) for campaign sequences while maintaining the original "Calm" aesthetic. All "Industrial/Tactile" aesthetic experiments have been reverted.

## 2. Database Schema Evolution
The outreach logic now relies on graph traversal rather than list iteration.
- **`sequence_nodes`**: (Formerly `sequence_steps`) Stores node types (`trigger_start`, `action_linkedin_dm`, `action_whatsapp`, `action_email`, `condition_replied`, `delay`) and UI coordinates.
- **`sequence_edges`**: Defines the connections between nodes, including source handles (`true`, `false`, `default`) for branching.
- **`leads`**: Added `current_node_id` (UUID) for state tracking and `replied_at` (TIMESTAMPTZ) for conditional evaluation.
- **`queue`**: Now references `node_id` instead of `step_id`.

## 3. Backend Orchestration
- **`services/sequencer.py`**: Rewritten as a graph traversal engine.
    - `schedule_sequence()`: Initiates the flow by finding the `trigger_start` node.
    - `queue_next_nodes()`: Finds outgoing edges and queues the next actions or recursively evaluates conditions.
    - `evaluate_conditions()`: Re-evaluates a lead's position in the graph when external events (like replies) occur.
- **`services/dispatcher.py`**:
    - Handlers now use `node_id` to fetch configuration from `sequence_nodes.data`.
    - Added Unipile unified handlers for **WhatsApp**, **Instagram**, and **Telegram**.
    - **Note**: Email strictly uses the native SMTP wrapper in `services/email.py`.
- **`routers/webhooks.py`**: New endpoint `POST /webhooks/unipile` handles `message.received`. It updates `leads.replied_at` and triggers `sequencer.evaluate_conditions()`.

## 4. Frontend: Dual-Mode Builder
The sequence editor in `Campaigns.tsx` now supports two distinct user experiences:
- **Sequential mode**: A linear list (re-implemented in `SequentialBuilder.tsx`) that automatically "compiles" into a graph (Node -> Edge -> Node) behind the scenes.
- **Canvas mode**: A full nodal flow editor powered by `@xyflow/react`.
- **Logic**: Both builders use the same `useSaveGraph` hook, sending a unified `nodes` and `edges` payload to the backend.

## 5. Unipile Integration Details
- **WhatsApp**: Uses `phone_number@s.whatsapp.net` as the `attendee_id`.
- **Unified Messaging**: All messaging channels use the `POST /api/v1/chats` endpoint.
- **Account Mapping**: One Unipile `account_id` per channel/number.

## 6. Pending Logic (For Claude)
- **Nested Voice Flows**: The UI needs a sub-canvas for the `action_voice` node to build internal Retell AI conversation flows.
- **Node-to-Retell Sync**: Backend logic to call `POST /create-conversation-flow` when a voice node is saved in Omni.
- **Advanced Conditions**: Implementation of custom logical equations in `ConditionNode` (beyond just "Replied").

## 7. Deployment Context
- **VPS**: `145.223.21.222`
- **Path**: `/home/omni-outreach`
- **Commands**: `docker compose up -d --build` (applied via SSH).
- **Environment**: `.env` is synced manually; `.env.example` is the source of truth for keys.
