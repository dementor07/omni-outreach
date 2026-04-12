---
title: ADR — Omnichannel Logic Loops
category: decisions
tags: [ADR, omnichannel, routing, tags, state-machine]
sources: []
updated: 2026-04-12
---

# ADR: Omnichannel Logic Loops

**Date:** 2026-04-12
**Status:** Accepted

## Context

The initial outreach logic was tightly coupled to linear sequences (e.g., Email 1 -> Email 2) or strictly segregated by channel. However, true omnichannel outreach requires the ability to seamlessly route a lead between mediums (LinkedIn, WhatsApp, Email, Voice) based on their behavior or channel-specific errors. 

For example, if an email bounces, the lead should be instantly routed to a LinkedIn Invite. If a Voice Call reveals the prospect wants written information, they should be routed to an Email node.

## Decision

We will use the **Event-Driven State Machine** combined with our generalized **Control and Condition Nodes** to build omnichannel logic loops, rather than hardcoding cross-channel logic into the dispatchers.

### 1. Tag-Based State Routing
Instead of creating dozens of highly specific condition nodes (e.g., `condition_voice_call_failed`), we utilize the `tags` array on the `leads` table.
- **Actions**: `action_add_tag`, `action_remove_tag`.
- **Conditions**: `condition_tag_exists`.

This allows operators to build loops: e.g., if a voice call ends in a specific state (handled via Retell webhook), the webhook adds a `send_whatsapp` tag to the lead and wakes them up. The very next node in the graph is `condition_tag_exists` checking for `send_whatsapp`, routing them directly to the `action_whatsapp` node.

### 2. Universal Event Listeners
Listener nodes (e.g., `event_email_opened`, `event_link_clicked`) park the lead and act as universal checkpoints. These listeners are not constrained by the previous channel. A lead can receive a LinkedIn DM containing a link, park at `event_link_clicked`, and upon clicking the link, be routed down the `True` branch to trigger an immediate `action_voice` call while their intent is highest.

### 3. A/B Split Testing Across Channels
The `split` (A/B Test) control node is strictly channel-agnostic. It routes 50% of traffic down Path A and 50% down Path B. This empowers operators to test a purely LinkedIn-driven loop against a purely Email-driven loop to determine the highest converting medium for a specific audience.

### 4. Terminal States
The `end` control node formally terminates a loop, setting the lead's status to `stopped`. This prevents "zombie leads" that fall off the graph without a formal conclusion.

## Consequences

- **Pros**: Infinite flexibility. Operators can build highly complex, looping workflows that switch channels effortlessly. The backend dispatcher remains completely unaware of the larger graph topology—it just executes the tasks it receives.
- **Cons**: The visual complexity of the DAG in the `canvas-editor` can quickly become overwhelming for users building massive cross-channel loops. UX mitigation (like grouping or subflows) will be required.

## Related Pages
- [[sequence-engine]]
- [[channels]]
