---
title: Reply Intent Timeout
category: architecture
tags: [decisions, sequence-engine, durability]
sources: [wiki/architecture/sequence-engine.md, wiki/decisions/human-approval-and-reply-intent.md]
updated: 2026-04-25
---

# ADR: Reply Intent Timeout

- **Status:** Accepted (shipped 2026-04-24, cron registration fixed 2026-04-25, semantics clarified 2026-04-28)
- **Context:** The `condition_reply_intent` node evaluates incoming replies (interested, not interested, etc.). However, if a lead never replies — or, more commonly, if their reply arrives via the Unipile stream path which currently doesn't classify (see [[human-approval-and-reply-intent]]) — they are parked at this node indefinitely without a fallback path. This represents a durability bug in the workflow sequence.
- **Decision:**
  1. Add a `timeout_days` field to the `condition_reply_intent` node configuration (defaults to 7).
  2. Add a `timeout` output handle to the frontend `ReplyIntentNode`.
  3. Implement a worker cron job `cron_reply_intent_timeout` registered at `minute={0, 30}` (i.e. every 30 minutes). The job scans for leads parked at `condition_reply_intent` whose latest **outbound** `queue.sent_at` is older than `timeout_days`, and routes them via the `timeout` handle.
  4. Verify the cron is actually registered in `WorkerSettings.cron_jobs`. (The original 6f3c0c0 commit defined the function but missed the registration, so the cron never ran. Patched in 42a63ad.)
- **What the timeout actually measures:** elapsed time since the lead's most recent successful outbound send (`MAX(queue.sent_at) WHERE lead_id = $lead AND status = 'sent'`). It is **not** "time spent at the node." Implication: if a lead reaches `condition_reply_intent` via a pure-condition branch with no preceding outbound action, they will have no `sent_at`, the cron skips them, and the timeout never fires. Designs should always have at least one outbound `action_*` upstream of `condition_reply_intent` for the timeout to function.
- **Rationale:** Ensures guaranteed progression through the DAG for leads we have actually contacted, avoiding indefinite parking and silent campaign failure for non-responsive targets.
- **Consequences:** Requires frontend UI updates (ConfigSidebar, node handles) and backend sequencer/worker coordination. Leads will naturally progress without manual intervention — once an outbound has been logged for them.
- **Verification recipe:** From inside the worker container, `python -c "from app.worker.tasks import WorkerSettings; [print(c.name, c.minute, c.second) for c in WorkerSettings.cron_jobs]"` should list `cron:cron_reply_intent_timeout {0, 30} 0`. Use this whenever a new cron is added — the function-existence-vs-cron-registration gap bit us once.
- **Related Pages:** [[sequence-engine]], [[human-approval-and-reply-intent]], [[worker]]
