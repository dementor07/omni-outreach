---
title: Canvas Editor
category: product
tags: [canvas, ReactFlow, xyflow, UX, sequences, telemetry, bandit]
sources: []
updated: 2026-04-19
---

# Canvas Editor

`frontend/src/pages/Campaigns.tsx` — sequence tab when `campaign.sequence_mode === 'canvas'`

## Node Types & Components

All 23 `node_type` values accepted by the backend (`NodeType` Literal in `sequences.py`) and rendered by the frontend:

| node_type | Component | Palette Group | Notes |
|-----------|-----------|---------------|-------|
| `trigger_start` | `TriggerNode` | *(palette header button)* | Dark slate card, Zap icon, label "Trigger / Sequence Start". No target handle. Every sequence has exactly one. |
| `action_linkedin_invite` | `ActionNode` | LinkedIn | Sends connection request. Sequencer auto-parks until accepted. |
| `action_linkedin_dm` | `ActionNode` | LinkedIn | Sends direct message to an accepted connection. |
| `action_linkedin_inmail` | `ActionNode` | LinkedIn | Premium InMail — bypasses connection requirement. |
| `action_linkedin_profile_view` | `ActionNode` | LinkedIn | Views prospect profile; populates `linkedin_distance`. |
| `action_email` | `ActionNode` | Messaging | Native SMTP send. Account selector in ConfigSidebar. |
| `action_whatsapp` | `ActionNode` | Messaging | WhatsApp message via Unipile. |
| `action_sms` | `ActionNode` | Messaging | **Stubbed** — SMS send. No dispatcher handler yet. |
| `action_instagram` | `ActionNode` | Messaging | **Stubbed** — dispatcher logic pending. |
| `action_telegram` | `ActionNode` | Messaging | **Stubbed** — dispatcher logic pending. |
| `action_voice` | `ActionNode` | Voice | Retell AI call. Standard/Flow mode toggle in ConfigSidebar. |
| `action_add_tag` | `ActionNode` | Actions | Adds a tag to the lead record. |
| `action_remove_tag` | `ActionNode` | Actions | Removes a tag from the lead record. |
| `action_webhook` | `ActionNode` | Actions | **Stubbed** — Webhook/CRM push. No dispatcher handler yet. |
| `condition_replied` | `ConditionNode` | Conditions | True/False fork: has the lead replied on any channel? Icon: GitBranch. |
| `condition_linkedin_distance` | `ConditionNode` | Conditions | True/False fork: is 1st-degree connection? Requires profile view upstream. |
| `condition_tag_exists` | `ConditionNode` | Conditions | True/False fork: does a specific tag exist on this lead? |
| `event_invite_accepted` | `EventNode` | Events | Waits/fires when LinkedIn invite is accepted. Icon: Bell. |
| `event_email_opened` | `EventNode` | Events | Fires when email open tracking pixel fires. |
| `event_link_clicked` | `EventNode` | Events | Fires when a tracked link in an email is clicked. |
| `delay` | `DelayNode` | Flow | Inline number input for `delay_days`. |
| `split` | `SplitNode` | Flow | A/B bandit. Icon: Shuffle. Shows "Bandit Active" + per-arm win rate % once learned. See [[auto-optimization-engine]]. |
| `end` | `EndNode` | Flow | Rose terminal card. Removes lead from active processing. |

`ActionNode` uses the `ConfigSidebar` for all configuration. `ConditionNode` shows a GitBranch icon and a True/False output handle pair. `EventNode` shows the palette icon (Bell fallback) with a single source handle.

## NodePalette Groups

The left-side palette (`w-52`, scrollable, `maxHeight: calc(100vh - 160px)`) groups nodes into 7 sections:

| Heading | Types |
|---------|-------|
| LinkedIn | invite, dm, inmail, profile_view |
| Messaging | email, whatsapp, sms, instagram, telegram |
| Voice | voice |
| Actions | add_tag, remove_tag, webhook |
| Conditions | replied, linkedin_distance, tag_exists |
| Events | invite_accepted, email_opened, link_clicked |
| Flow | delay, split, end |

## Edge Types

| type | Component | When used |
|------|-----------|-----------|
| `custom` | `CustomEdge` | Default. Bezier with ✕ delete button on select. |
| `telemetry` | `TelemetryEdge` | Active when Live mode on. Heat-colored, floating pill, dashed on backpressure. See [[telemetry-overlay]]. |

## Canvas UX Controls

Top-right `<Panel>` contains two buttons:

| Button | Style | Behaviour |
|--------|-------|-----------|
| **Live** | Emerald when active, white/slate when inactive | Toggles the telemetry polling loop; edge types switch between `custom` and `telemetry` |
| **Save Canvas** | Sky-500 with shadow-sky-100 | Calls `saveGraph.mutate()` → `POST /sequences/save`. Previously labelled "Deploy Canvas" — renamed Apr 2026. |

`btn-tactile` CSS utility class (defined in `index.css` `@layer components`) is applied to both buttons for consistent press feedback (`active:scale-[0.97]`).

## SplitNode — Bandit Display

Reads `node.data.weights` (`{true: {alpha, beta}, false: {alpha, beta}}`).
- No data or default (sum ≤ 4): shows "Learning (50/50)"
- Learned: shows "Bandit Active" + `Math.round(alpha/(alpha+beta)*100)% win rate` per arm

## ConfigSidebar

Right-side panel opens on node click (`selectedNodeId`). Fields:
- All: node type label
- `delay`: `delay_days` input (calls `updateNodeData`)
- `action_email`: account selector + subject + body
- `action_voice`: Standard/Flow toggle + agent + prompt editor / Retell editor link
- Other action nodes: body textarea + template save

## Serialization (Critical)

React callbacks are stripped before DB save:
```ts
const { onChange, onDelete, onEditTemplate, ...serializableData } = n.data as any
```
Prevents non-serializable functions persisting to `sequence_nodes.data JSONB`.

## Save / Load

- Load: `GET /sequences/{campaign_id}` → React Flow nodes + edges
- Save: `POST /sequences/save` — full replace (delete + re-insert all nodes/edges for campaign)

## Live Telemetry Toggle

"Live" button in Panel (top-right). When active:
- Polls `GET /sequences/{id}/telemetry` every 5s
- Edges switch to `type: 'telemetry'`, colored by activity/backpressure
- Radio icon pulses while active

## Related Pages
- [[sequence-engine]]
- [[telemetry-overlay]]
- [[auto-optimization-engine]]
- [[voice-node]]
