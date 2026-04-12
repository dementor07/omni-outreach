---
title: Event Bus Architecture
category: architecture
tags: [kafka, redis-streams, webhooks, scalability, state-machine]
sources: []
updated: 2026-04-12
---

# Event Bus Architecture (Scalability Layer)

As Omni transitions into a fully **Event-Driven State Machine**, the volume of inbound signals (webhooks) will grow exponentially. Processing these synchronously against the PostgreSQL database creates a severe bottleneck.

## The Problem: Webhook Bursts
When a campaign sends 5,000 emails, open tracking pixels and link clicks (`event_email_opened`, `event_link_clicked`) can fire simultaneously in massive bursts. 
If `/webhooks/unipile` or our email tracking endpoints directly execute `UPDATE leads SET current_node_id...` for every single request, we risk:
1. Database connection pool exhaustion.
2. Unacceptable latency on webhook responses (causing third-party providers to timeout and retry, compounding the issue).
3. Deadlocks when the [[dispatcher]] and webhook handlers compete for `leads` table rows.

## The Solution: Asynchronous Event Ingestion

We will implement an intermediary **Event Bus** (e.g., Redis Streams or Apache Kafka) to decouple ingestion from execution.

### 1. Ingestion Layer (Fast & Dumb)
The FastAPI webhook endpoints will do absolutely zero database querying. 
When a payload arrives:
```python
@router.post("/webhooks/unipile")
async def unipile_webhook(request: Request):
    payload = await request.json()
    # Instantly push to Redis Stream 'omni_inbound_events'
    await redis.xadd('omni_inbound_events', {'source': 'unipile', 'payload': json.dumps(payload)})
    return {"status": "queued"}
```
*Latency: < 5ms.*

### 2. Stream Processor (The Router)
A dedicated background worker group (the "Event Router") consumes from `omni_inbound_events`.
- It parses the payload, identifies the `lead_id` (via `chat_id` mapping or email address).
- It batches updates to the database (e.g., updating `replied_at` for 100 leads in a single transaction).
- It places a high-priority job onto the ARQ queue: `evaluate_conditions(lead_id)`.

### 3. State Transition Execution
The ARQ worker picks up `evaluate_conditions`, checks the DAG blueprint via the [[sequence-engine]], and executes the state transition, pushing the lead to the next node.

## Benefits
- **Backpressure Handling**: The Redis Stream acts as a shock absorber. Even if 10,000 replies come in at exactly 9:00 AM, FastAPI acknowledges them instantly, and the stream processor works through them at a safe, configurable rate.
- **Retryability**: If the database goes down momentarily, the stream processor pauses. The raw webhooks are safely persisted in Redis and won't be lost.

## Related Pages
- [[sequence-engine]]
- [[system-overview]]
