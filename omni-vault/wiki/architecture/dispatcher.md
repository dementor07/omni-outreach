---
title: Dispatcher
category: architecture
tags: [queue, worker, concurrency, locking, channels]
sources: []
updated: 2026-04-21
---

# Dispatcher

`backend/app/services/dispatcher.py`

The dispatcher is Omni's execution engine. It locks ready queue rows, executes the correct handler, logs an immutable event, and advances the graph. It runs inside the arq worker on the `dispatch_queue` cron.

## Constants

| Name | Value |
|------|-------|
| `BATCH_SIZE` | 20 tasks per run |
| `MAX_RETRIES` | 3 |
| `RETRY_DELAY_SECONDS` | 300 seconds |

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

`SKIP LOCKED` prevents duplicate processing when more than one worker is present.

## Active Hours Gate

Every task passes through `_in_active_hours(campaign)`. If the campaign is outside its local send window, the task is rescheduled to `_next_window_start()` and released back to `queued`.

## Simulation Mode

If `campaign.simulation_mode = TRUE`, the dispatcher logs `simulated_{channel}`, marks the task sent, and advances the DAG without making external calls.

## Queue Handlers

| `queue.channel` | Handler | Key Behavior |
|-----------------|---------|-------------|
| `linkedin_invite` | `_handle_linkedin_invite` | Enforces per-account caps, resolves provider IDs, sends invite, sets `invited_at` |
| `linkedin_dm` | `_handle_linkedin_dm` | Renders body, starts or continues LinkedIn chat |
| `linkedin_inmail` | `_handle_linkedin_inmail` | Sends/logs InMail intent with subject and body |
| `linkedin_profile_view` | `_handle_linkedin_profile_view` | Reads profile data and stores `linkedin_distance` |
| `whatsapp` | `_handle_whatsapp` | Sends WhatsApp chat message through Unipile |
| `instagram` | `_handle_instagram` | Sends Instagram DM, tolerates invalid-recipient cases by tagging and advancing |
| `telegram` | `_handle_telegram` | Sends Telegram DM using username/phone resolution |
| `email` | `_handle_email` | Sends via SMTP, decrypting stored SMTP credentials when needed |
| `voice` | `_handle_voice` | Calls Retell AI, including flow-mode conversation IDs when configured |
| `sms` | `_handle_sms` | Sends Twilio SMS using rendered template body and logs `sms_sent` |
| `webhook` | `_handle_webhook` | Sends POST/PUT/PATCH to node-configured URL with optional rendered body template |
| `add_tag` | `_handle_add_tag` | Appends tag idempotently |
| `remove_tag` | `_handle_remove_tag` | Removes tag from `leads.tags[]` |
| `enrich` | `_handle_enrich` | Calls lead-source provider `enrich()`, merges only missing fields, logs `lead_enriched` |

## Post-Execution Contract

Every successful handler performs the same three steps:

1. `_log_event(lead_id, campaign_id, event_type, channel)`
2. `_mark_sent(queue_id)`
3. `sequencer.queue_next_nodes(lead_id, node_id)`

That uniform contract is what keeps delivery channels, webhook pushes, and internal actions like enrichment behaving like one graph engine.

## Retry and Dead-Letter Logic

`_fail_task()` handles all exceptions:

- `retry_count < MAX_RETRIES`: reschedule with backoff and return to `queued`
- `retry_count >= MAX_RETRIES`: mark `failed` and persist the final dead-letter reason on the queue row

## Background Helpers

### `_queue_invitations()`

Every 5 minutes, assigns LinkedIn accounts to eligible leads and inserts `linkedin_invite` tasks for active campaigns in active hours.

### `_check_acceptances()`

Every 5 minutes, polls Unipile for accepted connections, sets `accepted_at`, logs `invite_accepted`, and calls `sequencer.schedule_sequence(lead_id)`.

## Related Pages

- [[sequence-engine]]
- [[channels]]
- [[lead-sources-ui]]
- [[unipile-integration]]
- [[event-bus-architecture]]
