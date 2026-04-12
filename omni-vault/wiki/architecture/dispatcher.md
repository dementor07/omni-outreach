---
title: Dispatcher
category: architecture
tags: [queue, worker, concurrency, locking]
sources: []
updated: 2026-04-12
---

# Dispatcher

The dispatcher is the execution engine of Omni. It runs as a continuous background worker process, picking up tasks scheduled by the [[sequence-engine]] and executing the actual outreach across various [[channels]].

## Queue Locking Mechanism

To support horizontal scaling (multiple worker containers running simultaneously), the dispatcher uses strict PostgreSQL pessimistic locking.

```sql
WITH candidates AS (
    SELECT q.id FROM queue q
    JOIN campaigns c ON c.id = q.campaign_id
    WHERE q.status='queued' AND q.scheduled_at <= NOW() AND c.status='active'
    ORDER BY q.scheduled_at LIMIT $1 FOR UPDATE OF q SKIP LOCKED
)
UPDATE queue SET status='locked', locked_at=NOW(), locked_by=$2
FROM candidates WHERE queue.id=candidates.id RETURNING queue.*
```
This ensures no two workers ever process the same lead task concurrently.

## Channel Handlers

Once locked, `_process_task(task)` routes the task based on its `channel`:
- `linkedin_invite`: Calls `_handle_linkedin_invite`
- `linkedin_dm`: Calls `_handle_linkedin_dm`
- `email`: Calls `_handle_email`
- `whatsapp`: Calls `_handle_whatsapp`
- `voice`: Calls `_handle_voice`

## Post-Execution

After a task is successfully executed:
1. `_mark_sent(task_id)` updates the queue status to `sent`.
2. `_log_event()` writes an immutable record to the `events` table.
3. `sequencer.queue_next_nodes()` is called to evaluate the outgoing edges from the completed node and queue the next steps in the DAG.

If a task fails, `_fail_task` increments the `retry_count` and reschedules it with a backoff, or marks it `failed` if `MAX_RETRIES` (3) is exceeded.
