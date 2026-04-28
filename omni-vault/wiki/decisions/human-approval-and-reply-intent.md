---
title: "ADR: Human Approval, Reply-Intent Branching, Hot-Lead Alerts"
category: decisions
tags: [sequence-engine, approvals, reply-intent, notifier, parking, ADR]
sources: [raw/Clippings/Cold Outreach Script Fix.md]
updated: 2026-04-23
---

# ADR: Human Approval, Reply-Intent Branching, Hot-Lead Alerts

## Status

Accepted — shipped 2026-04-23 in migration 004 + commit `ef7440c`.

## Context

The sequence engine before this ADR could automate LinkedIn + Email + Voice outreach end to end, but three gaps kept forcing operators to babysit the queue:

1. **No human gate.** High-value messages (InMails, escalation emails) had no way to require sign-off before firing. The only workaround was `simulation_mode` on the whole campaign.
2. **Replies were opaque to the graph.** `condition_replied` only told us "they replied" — not whether they were interested, bouncing, out-of-office, or unsubscribing. Everyone landed on the same True branch.
3. **Hot leads disappeared into the inbox.** When a lead showed buying intent, nobody found out until the operator happened to open the inbox hours later.

## Decision

Three new node types plus one new backing table pattern. All three live inside the same traversal contract as the existing nodes — no special-case loops in the engine.

### `human_approval` — blocking human gate

- Palette category: Actions (conceptually a state-mutating side effect, same as `add_tag`).
- Handles: `approve`, `reject`.
- Entry behavior (in `queue_next_nodes`):
  - `INSERT INTO approvals (campaign_id, lead_id, node_id, title, payload)` — idempotent on `(lead_id, node_id)` while status is `pending`.
  - Parks the lead: `UPDATE leads SET current_node_id = <this node>`.
  - Does not self-advance.
- Resume path: `POST /approvals/{id}/resolve` → `sequencer.resume_from_approval(lead_id, approval_id, resolution)` → `queue_next_nodes(lead_id, current_node_id, 'approve' | 'reject')`.
- `evaluate_conditions` does not pick up this node type. It is only unparked through the approvals router, because the signal originates from human input, not from lead state change.

### `condition_reply_intent` — intent-aware routing
- Palette category: Conditions.
- Handles: `positive`, `negative`, `neutral`, `out_of_office`, `unsubscribe`, `bounce` (one per category produced by `services/reply_classifier.py`), plus `timeout` (see [[reply-intent-timeout]]).
- Entry behavior:
  - If `lead.last_reply_category` is already set, branch on it immediately.
  - Otherwise park: `UPDATE leads SET current_node_id = <this node>`.
- Resume path — there are **two**, and only one of them currently classifies:
  - **Generic HTTP webhook** (`POST /webhooks/events/inbound`, `routers/webhooks.py`): on `event_type=='reply'` it calls `classify_reply(...)` and writes `last_reply_text/category/confidence/at` onto the lead, then queues a `omni_sequence_events` Redis stream entry. This path picks up the parked node correctly.
  - **Unipile stream** (`worker/stream_processor.py::_process_unipile_payload`): handles inbound LinkedIn / WhatsApp / IG / TG replies. As of 2026-04-28 it sets `replied_at` and `status='replied'` and calls `evaluate_conditions`, but it does **not** call `classify_reply` and does **not** write `last_reply_*`. Result: leads receiving Unipile-routed replies park indefinitely at `condition_reply_intent` until either the timeout cron fires or the lead is unparked manually. **Fix tracked separately.**

### `action_hot_lead_alert` — fan-out notification

- Palette category: Actions.
- Queued like any other delivery channel; dispatcher handler is `_handle_hot_lead_alert`.
- Renders `title`/`body` templates against the lead + campaign, calls `notifier.dispatch_alert(title, body, context, channel_ids)`, logs `hot_lead_alert` with the delivered count.
- `channel_ids` is optional on the node — blank means fan out to every active channel.

## Storage

Migration 004 adds:

- `leads.last_reply_text TEXT`, `last_reply_category TEXT`, `last_reply_confidence REAL`, `last_reply_at TIMESTAMPTZ`.
- `approvals` table: `id`, `campaign_id`, `lead_id`, `node_id`, `title`, `payload JSONB`, `status`, `resolution`, `resolved_by`, `resolved_at`, `created_at`. Index `idx_approvals_status_campaign(status, campaign_id, created_at)`.
- `notification_channels` table: `id`, `channel_type`, `name`, `config JSONB`, `is_active`, `created_at`.

## Rationale

### Why cache the reply onto the lead instead of querying `events`?

`condition_reply_intent` is evaluated in the hot path every time a lead traverses the graph. Joining `events` with a reverse-time sort on every traversal was the obvious alternative but expensive at scale, and the classifier already runs once on webhook receipt. Caching the latest classification on the lead gives us an O(1) branch decision.

The trade-off: we only track the most recent reply. Historical intent sequences (did they go negative, then positive?) live in `events` and are not available to the graph. Acceptable — the graph should react to the current state, not replay history.

### Why a table for approvals instead of a JSONB blob on the lead?

Operators need an inbox view across campaigns, a count badge, and a status filter. That is a list view, and list views need rows. A JSONB array on the lead would have required either a per-lead scan or a materialized index. The table pays for itself on the inbox query alone.

### Why globally scoped `notification_channels`?

The original instinct was to scope channels per campaign. We went global because:

- 95% of the time "hot lead alerts" are routed to the same place (one Slack channel per team).
- Per-campaign scoping would have forced the UI to duplicate the same channel config across every campaign.
- We can add an `action_hot_lead_alert.channel_ids` override per node if a campaign wants a different destination — which is the actual mechanism we shipped.

### Why no retries in the notifier?

Slack/email delivery failure is not a lead-state-change event. If the alert fails, we don't want to block the lead's DAG traversal or clutter the queue with retry rows. The caller logs the delivered count; if we later need guaranteed delivery we can swap `dispatch_alert` to enqueue instead of calling inline.

## Consequences

- Operators now have a real inbox for high-stakes sends, scoped by pending/approved/rejected.
- Campaigns can branch meaningfully on replies, enabling patterns like "positive → book call, negative → send unsubscribe confirmation, bounce → stop sequence".
- Hot leads surface in Slack/email within seconds of hitting an alert node.
- Migration 004 is backward-compatible — the new columns and tables are all additive.
- The approvals table will grow unbounded; no retention policy yet. When it becomes a problem we'll add an archival job.

## Related Pages

- [[sequence-engine]]
- [[dispatcher]]
- [[notifier]]
- [[approvals-page]]
- [[settings-page]]
- [[system-gaps-sprint]]
