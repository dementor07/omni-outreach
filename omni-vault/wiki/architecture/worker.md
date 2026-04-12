---
title: Worker (arq + Cron Jobs)
category: architecture
tags: [worker, arq, cron, redis, background]
sources: []
updated: 2026-04-12
---

# Worker

`backend/app/worker/tasks.py`
`backend/app/worker/stream_processor.py`

Background process using **arq** (async Redis queue). Connects to `redis://redis:6379`.

## Cron Schedule

| Function | Schedule | What it does |
|----------|----------|-------------|
| `dispatch_queue` | Every 30s (`second={0,30}`) | Locks + processes up to 20 queued tasks via `dispatcher.run_once()`. Also calls `dispatcher._queue_invitations()`. |
| `check_acceptances` | Every 5 min | Polls Unipile for newly accepted connections → triggers `sequencer.schedule_sequence()`. |
| `process_stream_events` | Every 5s | Reads from Redis Stream `omni_inbound_events`, routes to `_process_unipile_payload()`. |
| `optimize_splits` | Every 10 min | Runs Thompson Sampling weight updates on all active split nodes via `optimization.run_optimization()`. |

## Stream Processor

`stream_processor.py` — consumer group `event_router_group`, consumer `worker_1`.

Processes `message.received` events from Unipile webhooks (buffered via Redis Stream `omni_inbound_events` by the [[event-bus-architecture]]).

On inbound message:
1. Find lead by `chat_id`
2. `UPDATE leads SET replied_at=NOW(), status='replied'`
3. Insert into `inbound_messages` table
4. Call `sequencer.evaluate_conditions(lead_id)` → resumes parked condition/event nodes

## Worker Config

```python
class WorkerSettings:
    redis_settings = RedisSettings(host="redis")
    max_jobs = 1       # one concurrent job slot — serialized execution
    job_timeout = 300  # 5 min timeout per job
```

`max_jobs=1` means jobs run serially. Safe for the dispatcher's `SKIP LOCKED` pattern.

## Startup / Shutdown

`on_startup`: initializes asyncpg pool + Redis client
`on_shutdown`: closes both

## Related Pages
- [[dispatcher]]
- [[event-bus-architecture]]
- [[sequence-engine]]
- [[auto-optimization-engine]]
