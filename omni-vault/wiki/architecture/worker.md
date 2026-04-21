---
title: Worker (arq + Cron Jobs)
category: architecture
tags: [worker, arq, cron, redis, background]
sources: []
updated: 2026-04-21
---

# Worker

`backend/app/worker/tasks.py`
`backend/app/worker/stream_processor.py`

Background process using **arq**. It owns queue dispatch, acceptance checks, inbound event processing, split optimization, and scheduled lead generation.

## Redis / Connection Model

- Worker startup initializes the asyncpg pool and Redis client explicitly.
- `WorkerSettings.redis_settings = RedisSettings(host="redis", password=_redis_password)` mirrors the authenticated Redis setup used in Docker.
- The app-side Redis client comes from `settings.get_redis_url()` so background tasks and runtime API code share the same connection pattern.

## Cron Schedule

| Function | Schedule | What it does |
|----------|----------|-------------|
| `dispatch_queue` | Every 30 seconds (`second={0,30}`) | Locks and processes ready queue tasks via `dispatcher.run_once()`, then opportunistically queues LinkedIn invites |
| `check_acceptances` | Every 5 minutes | Polls for accepted LinkedIn invites and resumes sequences |
| `process_stream_events` | Every 5 seconds | Consumes Redis Stream webhook events and updates lead state |
| `optimize_splits` | Every 10 minutes | Runs Thompson Sampling weight updates |
| `cron_lead_gen` | Every 5 minutes | Scans enabled `lead_gen_configs` with `cron_schedule` and fires due source runs with `triggered_by="schedule"` |

## Scheduled Lead Gen

`cron_lead_gen(ctx)` is the key Apr 2026 addition:

- Imports `croniter` lazily so the worker can log a clear warning if the dependency is missing.
- Reads enabled configs where `cron_schedule IS NOT NULL`.
- Uses `last_run_at` as the schedule base, falling back to "one year ago" so newly scheduled configs can fire immediately when due.
- Calls `run_lead_gen(campaign_id, config_id, triggered_by="schedule")`.

This is what turns [[lead-sources-ui]] from a manual trigger screen into an autonomous intake loop.

## Stream Processor

`stream_processor.py` uses Redis consumer group `event_router_group` and consumer `worker_1`.

For inbound `message.received` events buffered on `omni_inbound_events`:

1. Find the lead by `chat_id`
2. Set `replied_at=NOW()` and status `replied`
3. Insert the inbound payload into `inbound_messages`
4. Call `sequencer.evaluate_conditions(lead_id)` to resume parked graph nodes

## Worker Config

```python
class WorkerSettings:
    redis_settings = RedisSettings(host="redis", password=_redis_password)
    max_jobs = 1
    job_timeout = 300
```

`max_jobs=1` keeps execution serialized and pairs cleanly with the dispatcher's `SKIP LOCKED` strategy.

## Startup / Shutdown

- `on_startup`: initialize DB pool and Redis
- `on_shutdown`: close DB pool and Redis cleanly

## Related Pages

- [[dispatcher]]
- [[lead-sources-ui]]
- [[event-bus-architecture]]
- [[sequence-engine]]
- [[auto-optimization-engine]]
