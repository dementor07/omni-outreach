---
title: Reply Intent Timeout
category: architecture
tags: [decisions, sequence-engine, durability]
sources: [wiki/architecture/sequence-engine.md, wiki/decisions/human-approval-and-reply-intent.md]
updated: 2026-04-24
---

# ADR: Reply Intent Timeout

- **Status:** Accepted
- **Context:** The `condition_reply_intent` node evaluates incoming replies (interested, not interested, etc.). However, if a lead never replies, they are parked at this node indefinitely without a fallback path. This represents a durability bug in the workflow sequence.
- **Decision:** 
  1. Add a `timeout_days` field to the `condition_reply_intent` node configuration.
  2. Add a `timeout` output handle to the frontend `ReplyIntentNode`.
  3. Implement a worker cron job that periodically scans for leads parked at `condition_reply_intent` nodes whose duration at the node exceeds `timeout_days`.
  4. Route these timed-out leads down the new `timeout` handle via the sequence engine.
- **Rationale:** Ensures guaranteed progression through the DAG for all leads, avoiding indefinite parking and silent campaign failure for non-responsive targets.
- **Consequences:** Requires frontend UI updates (ConfigSidebar, node handles) and backend sequencer/worker coordination. Leads will naturally progress without manual intervention.
- **Related Pages:** [[sequence-engine]], [[human-approval-and-reply-intent]]