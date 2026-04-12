---
title: Dispatcher
category: architecture
tags: [queue, worker, concurrency, locking, channels]
sources: []
updated: 2026-04-12
---

# Dispatcher

`backend/app/services/dispatcher.py`

The execution engine. Picks up locked queue tasks and calls the appropriate channel handler. Runs inside the arq worker on a 30-second cron (`dispatch_queue`).

## Constants

| Name | Value |
|------|-------|
| `BATCH_SIZE` | 20 tasks per run |
| `MAX_RETRIES` | 3 |
| `RETRY_DELAY_SECONDS` | 300 (5 min backoff) |

## Queue Locking

```sql
WITH candidates AS (
    SELECT q.id FROM queue q
    JOIN campaigns c ON c.id = q.campaign_id
    WHERE q.status='queued' AND q.scheduled_at <= NOW() AND c.status='active'
    ORDER BY q.scheduled_at LIMIT $BATCH_SIZE FOR UPDATE OF q SKIP LOCKED
)
UPDATE queue SET status='locked', locked_at=NOW(), locked_by=$worker_id
FROM candidates WHERE queue.id=candidates.id RETURNING queue.*
```

`SKIP LOCKED` prevents two workers from ever processing the same task. Safe for horizontal scaling.

## Active Hours Gate

Every task is gated by `_in_active_hours(campaign)` — checks `campaign.timezone`, `active_hours_start`, `active_hours_end`. If outside window, task is rescheduled to `_next_window_start()` and released.

## Simulation Mode

If `campaign.simulation_mode = TRUE`, all tasks are logged as `simulated_{channel}` and marked sent without making any real API calls.

## Channel Handlers

| Channel | Handler | Key Behavior |
|---------|---------|-------------|
| `linkedin_invite` | `_handle_linkedin_invite` | Checks daily invite cap per account. Resolves `provider_id` from Unipile if missing. Calls `linkedin.send_invite()`. Sets `leads.invited_at`. |
| `linkedin_dm` | `_handle_linkedin_dm` | Renders template via `renderer.render()`. Opens new chat (`start_chat_with_message`) if no `lead.chat_id` else appends to existing. Sets `leads.chat_id`. |
| `linkedin_inmail` | `_handle_linkedin_inmail` | Renders subject + body. Logs inmail_sent event. MVP: logs intent, no real Unipile InMail call yet. |
| `linkedin_profile_view` | `_handle_linkedin_profile_view` | Calls `linkedin.get_profile()` which triggers a profile view. Captures `network_distance` → sets `leads.linkedin_distance`. |
| `whatsapp` | `_handle_whatsapp` | Same chat pattern as LinkedIn DM but uses phone number as attendee_id (`{phone}@s.whatsapp.net`). |
| `instagram` | `_handle_instagram` | Reads `node.data.instagram_account_id`. Resolves profile via Unipile. Catches `InvalidRecipientError` → tags lead `ig_dm_failed`, advances DAG anyway. |
| `telegram` | `_handle_telegram` | Reads `node.data.telegram_account_id`. Uses `telegram_username` or `phone` as identifier. Same error pattern as Instagram. |
| `email` | `_handle_email` | Reads `node.data.email_account_id`. Sends via `email.send_email()` with full SMTP config from `email_accounts` table. |
| `voice` | `_handle_voice` | Reads `node.data.voice_agent_id` + `node.data.mode`. Calls `voice.make_call()` with optional `conversation_flow_id` for Nested Flow mode. |
| `add_tag` | `_handle_add_tag` | Reads `node.data.tag`. Appends to `leads.tags[]` idempotently. |
| `remove_tag` | `_handle_remove_tag` | Reads `node.data.tag`. Removes from `leads.tags[]`. |

## Post-Execution (all handlers)

Every successful handler calls:
1. `_log_event(lead_id, campaign_id, event_type, channel)` → immutable write to `events` table
2. `_mark_sent(queue_id)` → `status='sent'`, `sent_at=NOW()`
3. `sequencer.queue_next_nodes(lead_id, node_id)` → traverses DAG outgoing edges

## Retry Logic (`_fail_task`)

- `retry_count < MAX_RETRIES`: reschedule with backoff, status back to `queued`
- `retry_count >= MAX_RETRIES`: status `failed`, `failure_reason` set

## Background Crons

### `_queue_invitations()` — every 5 min
For each active campaign in active hours: finds leads with no `linkedin_account_id`, assigns the least-loaded account (by daily invite count), inserts `linkedin_invite` task into queue.

### `_check_acceptances()` — every 5 min
Polls Unipile for `network_distance == FIRST_DEGREE` on invited leads. On detection: sets `leads.accepted_at`, logs `invite_accepted`, calls `sequencer.schedule_sequence(lead_id)`.

## Related Pages
- [[sequence-engine]]
- [[channels]]
- [[unipile-integration]]
- [[event-bus-architecture]]
