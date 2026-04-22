---
title: Canvas Editor
category: product
tags: [canvas, ReactFlow, xyflow, UX, sequences, telemetry, bandit, lead-gen]
sources: []
updated: 2026-04-21
---

# Canvas Editor

`frontend/src/pages/Campaigns.tsx` — the Sequence tab when `campaign.sequence_mode === 'canvas'`.

## Node Types & Components

All 27 backend-supported `node_type` values accepted by `backend/app/routers/sequences.py` and rendered by the frontend:

| node_type                      | Component       | Palette Group             | Notes                                                                                                                                                    |
| ------------------------------ | --------------- | ------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `trigger_start`                | `TriggerNode`   | *(palette header button)* | Dark slate card with Zap icon. Shows lead-source count, scheduled-source count, and in Live mode a `+N in 60s` source banner. Opens [[lead-sources-ui]]. |
| `action_linkedin_invite`       | `ActionNode`    | LinkedIn                  | Sends a connection request. Sequencer parks later on acceptance events.                                                                                  |
| `action_linkedin_dm`           | `ActionNode`    | LinkedIn                  | Sends a direct message to an accepted connection.                                                                                                        |
| `action_linkedin_inmail`       | `ActionNode`    | LinkedIn                  | Sends Premium InMail.                                                                                                                                    |
| `action_linkedin_profile_view` | `ActionNode`    | LinkedIn                  | Triggers a profile view and populates `linkedin_distance`.                                                                                               |
| `action_email`                 | `ActionNode`    | Messaging                 | Native SMTP send. ConfigSidebar selects the email account plus subject/body.                                                                             |
| `action_whatsapp`              | `ActionNode`    | Messaging                 | WhatsApp message via Unipile.                                                                                                                            |
| `action_sms`                   | `ActionNode`    | Messaging                 | Sends SMS through Twilio. Requires `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, and `TWILIO_FROM_NUMBER`.                                                  |
| `action_instagram`             | `ActionNode`    | Messaging                 | Instagram DM via Unipile account routing.                                                                                                                |
| `action_telegram`              | `ActionNode`    | Messaging                 | Telegram DM via configured account plus username/phone resolution.                                                                                       |
| `action_voice`                 | `ActionNode`    | Voice                     | Retell AI call. Standard vs Nested Flow mode in ConfigSidebar.                                                                                           |
| `action_webhook`               | `ActionNode`    | Actions                   | Sends POST/PUT/PATCH to a configured URL with rendered payload or lead JSON.                                                                             |
| `action_add_tag`               | `ActionNode`    | Actions                   | Adds a tag to the lead record.                                                                                                                           |
| `action_remove_tag`            | `ActionNode`    | Actions                   | Removes a tag from the lead record.                                                                                                                      |
| `action_enrich`                | `ActionNode`    | Actions                   | Calls a lead-source enrichment path and fills only missing lead fields.                                                                                  |
| `condition_replied`            | `ConditionNode` | Conditions                | True/False fork: has the lead replied on any channel?                                                                                                    |
| `condition_linkedin_distance`  | `ConditionNode` | Conditions                | True/False fork: is the lead 1st-degree? Usually follows profile view.                                                                                   |
| `condition_tag_exists`         | `ConditionNode` | Conditions                | True/False fork: does a specific tag exist?                                                                                                              |
| `condition_ai_screen`          | `ConditionNode` | Conditions                | Immediate AI screening gate using `screener.screen_lead()` and `screening_prompt`.                                                                       |
| `condition_lead_source`        | `ConditionNode` | Conditions                | Routes by `lead.source`; output handles map to configured providers plus `default`.                                                                      |
| `condition_has_field`          | `ConditionNode` | Conditions                | Immediate True/False branch based on presence of one lead field.                                                                                         |
| `event_invite_accepted`        | `EventNode`     | Events                    | Parks until the invite is accepted.                                                                                                                      |
| `event_email_opened`           | `EventNode`     | Events                    | Fires from the email open tracking pixel.                                                                                                                |
| `event_link_clicked`           | `EventNode`     | Events                    | Fires from tracked email link clicks.                                                                                                                    |
| `delay`                        | `DelayNode`     | Flow                      | Inline numeric input for `delay_days`.                                                                                                                   |
| `split`                        | `SplitNode`     | Flow                      | Thompson Sampling bandit. Shows learning vs live arm win rate.                                                                                           |
| `end`                          | `EndNode`       | Flow                      | Terminal node. Stops sequence execution for the lead.                                                                                                    |

`ActionNode` uses the `ConfigSidebar` for configuration. `ConditionNode` keeps the shared true/false branch layout but now inherits its label, icon, and accent colors from `NODE_PALETTE`, so nodes like `condition_ai_screen` and `condition_lead_source` no longer collapse into the same generic amber card. `EventNode` uses the palette icon with a single source handle.

## TriggerNode Enhancements

`trigger_start` is no longer a passive entry card.

- It queries `GET /lead-gen/configs/{campaignId}` to show how many sources feed the campaign.
- It shows a scheduled-source count badge when any source has `cron_schedule` set.
- In Live mode, it consumes `sources_recent` from `GET /sequences/{campaign_id}/telemetry` and renders per-source intake counts from the last 60 seconds.
- The source badge is clickable (`nodrag`) and navigates to [[lead-sources-ui]].

## NodePalette Groups

The left-side palette (`w-52`, scrollable, `maxHeight: calc(100vh - 160px)`) groups nodes into 7 sections:

| Heading | Types |
|---------|-------|
| LinkedIn | invite, dm, inmail, profile_view |
| Messaging | email, whatsapp, sms, instagram, telegram |
| Voice | voice |
| Actions | add_tag, remove_tag, webhook, enrich |
| Conditions | replied, linkedin_distance, tag_exists, ai_screen, lead_source, has_field |
| Events | invite_accepted, email_opened, link_clicked |
| Flow | delay, split, end |

## Edge Types

| type | Component | When used |
|------|-----------|-----------|
| `custom` | `CustomEdge` | Default Bezier edge with delete affordance on select |
| `telemetry` | `TelemetryEdge` | Active when Live mode is on; heat-colored with floating count pill and dashed backpressure state |

## Canvas UX Controls

Top-right panel contains two primary controls:

| Button | Style | Behaviour |
|--------|-------|-----------|
| **Live** | Emerald when active, white/slate when inactive | Polls telemetry every 5 seconds and swaps edge rendering to `telemetry` |
| **Save Canvas** | Sky-500 with `btn-tactile` styling | Calls `saveGraph.mutate()` → `POST /sequences/save` |

`btn-tactile` in `index.css` provides the shared press feedback used across campaign controls.

## SplitNode — Bandit Display

Reads `node.data.weights` (`{true: {alpha, beta}, false: {alpha, beta}}`).

- No meaningful data yet (sum ≤ 4): shows `Learning (50/50)`.
- Learned state: shows `Bandit Active` plus per-arm win rate derived from `alpha / (alpha + beta)`.

## ConfigSidebar

The right-side panel opens on node click (`selectedNodeId`). Important custom panels:

- `action_email`: email account selector, subject, body
- `action_voice`: Standard/Flow toggle, agent selector, Retell editor link
- `action_sms`: message body plus inline env-key requirement text
- `action_webhook`: URL, HTTP method, headers, optional `body_template`
- `action_enrich`: provider dropdown plus field selection for which missing fields to fill
- `condition_ai_screen`: `screening_prompt` textarea
- `condition_lead_source`: source checkboxes used to mint output handles
- `condition_has_field`: field selector (`email`, `linkedin_url`, `headline`, `company`, `phone`, `first_name`, `last_name`)
- `delay`: `delay_days`

## Serialization (Critical)

React callbacks are stripped before save:

```ts
const { onChange, onDelete, onEditTemplate, ...serializableData } = n.data as any
```

This prevents non-serializable functions from leaking into `sequence_nodes.data JSONB`.

## Save / Load

- Load: `GET /sequences/{campaign_id}` returns React Flow nodes and edges.
- Save: `POST /sequences/save` fully replaces all nodes and edges for the campaign.

## Implementation Note

The TypeScript layer still contains experimental `wait_until` and `goal` union members, and `Campaigns.tsx` includes a `WaitUntilNode` component. The backend `NodeType` contract in `sequences.py` does not accept those values, so they are not part of the shipped persisted graph model.

## Related Pages

- [[campaigns]]
- [[lead-sources-ui]]
- [[sequence-engine]]
- [[telemetry-overlay]]
- [[auto-optimization-engine]]
- [[voice-node]]
