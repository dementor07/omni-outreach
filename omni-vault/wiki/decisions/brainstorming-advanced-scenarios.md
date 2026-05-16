---
title: Brainstorming — Advanced Campaign Stress-Tests
category: product
tags: [brainstorming, stress-test, concurrency, complex-flows]
updated: 2026-05-05
---

# Advanced Campaign Stress-Tests: Where Omni Breaks

This document identifies complex, real-world campaign scenarios that require "Core Functionality Done Right" and exposes the architectural limits of the current "Agent-Centric" build.

## Scenario 1: The "Dual-Channel Blitz" (Concurrency Failure)
**The Goal:** A user wants to maximize the chance of a meeting by hitting a lead on LinkedIn and Email **simultaneously** the moment they are found.
- **The Flow:** Start -> [LinkedIn Invite AND Email 1].
- **The Requirement:** True parallel execution.
- **Current Failure:** The `sequencer.py` is a single-threaded graph traverser. It moves from Node A to Node B. There is no concept of a "Fork" node. 
- **User Impact:** Forced sequential delay. The user loses the "Blitz" effect.

## Scenario 2: The "Sub-Hour Urgency" (Time Constant Failure)
**The Goal:** A "Webinar Reminder" campaign. 
- **The Flow:** Lead registers (Webhook) -> Wait **15 Minutes** -> Send SMS with Link -> Wait **5 Minutes** before start -> Send WhatsApp.
- **The Requirement:** Granular time constants (`seconds`, `minutes`, `hours`).
- **Current Failure:** Every `delay` in the system is integer-based `days`. 
- **User Impact:** You cannot use Omni for time-sensitive events (Webinars, Flash Sales, Demo Reminders). It is a "Slow-Motion" tool only.

## Scenario 3: The "ABM Company-Group" (Relational Failure)
**The Goal:** Account-Based Marketing (ABM). If I message the CEO of Apple, I want to **automatically pause** all messages to the VP of Marketing at Apple to avoid looking like a spam bot.
- **The Requirement:** Cross-lead state awareness (Company-level locking).
- **Current Failure:** Leads are treated as isolated "Islands." The sequencer has no idea that Lead A and Lead B belong to the same company.
- **User Impact:** The company receives 10 messages to 10 different people at the same time. The user gets marked as spam and banned.

## Scenario 4: The "Smart Retry" (Error Handling Failure)
**The Goal:** If a LinkedIn DM fails because the lead's profile is private, **automatically** pivot to a Voice Call.
- **The Requirement:** Error-handle branching on Action Nodes.
- **Current Failure:** Action nodes have one output: "Default" (Success). Failure is a dead-end that requires manual intervention in a Queue that has no "Retry" button.
- **User Impact:** The sequence just "stops" for that lead. The user has to manually find the failure and figure out a workaround.

## Scenario 5: The "Dynamic Pricing" (Variable Logic Failure)
**The Goal:** Send an Email where the "Price" quoted is `{{base_price}} * {{employee_count}}`.
- **The Requirement:** A "Logic/Calculation" node.
- **Current Failure:** There is no way to perform math or logic on variables in the sequence. Variables are "static strings" only.
- **User Impact:** The user has to pre-calculate everything in a CSV before importing, making "Automated Scraper" leads useless for dynamic pricing.

## Scenario 6: The "Multi-Agent Hand-off" (Collaboration Failure)
**The Goal:** An AI Agent handles the first 3 replies. If the lead asks for a "Custom Demo," the AI **pauses** and notifies a **Human** to take over the specific LinkedIn thread.
- **The Requirement:** A "Human Takeover" state that halts the AI.
- **Current Failure:** The `reply_classifier.py` is a simple keyword matcher. It doesn't have a "Human Required" category that actually stops the engine.
- **User Impact:** The AI keeps "hallucinating" or sending automated follow-ups while the human is trying to type a manual reply.

---

## The "Constant" Audit (What's Missing?)

1. **Time Units**: `seconds`, `minutes`, `hours`, `days`, `weeks`. (Current: `days` only).
2. **Channel Concurrency**: `parallel_fork`, `race_condition_wait`. (Current: `linear` only).
3. **Data Types**: `string`, `number`, `boolean`, `json`. (Current: `string` only).
4. **Campaign Status**: `draft`, `active`, `paused`, `completed`, `archived`. (Current: `active`/`stopped` in a hidden field).
5. **Rate Limits**: `per_minute`, `per_hour`, `per_day` (per account vs per campaign). (Current: `per_day` only).

## Summary for Claude (The "Fixer")
To make this a "User Tool," we must move away from **"Linear Sequences of Strings"** and toward a **"Dynamic Logic Engine with Granular Orchestration."**


## Status Update (2026-05-16) — What's shipped since

Re-reviewed against the May 2026 codebase:

- **Scenario 1 — Concurrency**: PARTIAL. `control_parallel_fork` is now a real backend node type (see [[sequence-engine]]'s 30-node contract); `worker.max_jobs = 1` still serializes execution at the worker level (flagged in [[audit-2026-05-16]] as a critical gap).
- **Scenario 2 — Sub-hour urgency**: SHIPPED. `delay` nodes now accept `seconds`, `minutes`, `hours`, `days` (see "2026-05-05 Update: Core Restoration" in [[sequence-engine]]).
- **Scenario 3 — ABM company locking**: STILL OPEN. No cross-lead state awareness implemented yet.
- **Scenario 4 — Smart retry on action failure**: STILL OPEN. Action handlers still have one output. `_fail_task` retries up to 3 times then dead-letters; no error-branch handle.
- **Scenario 5 — Variable logic**: PARTIAL. `action_data_transform` ("Set Variable / AI") node exists in the canvas palette; computational expressions still limited.
- **Scenario 6 — Human takeover**: SHIPPED. `human_approval` node + `condition_reply_intent` with `unsubscribe`/`out_of_office` handles (see [[human-approval-and-reply-intent]]).
- **Constant audit**: time units shipped; campaign status (`draft` / `active` / `paused`) shipped per the 2026-05-05 ignition-switch work; rate-limit granularity still per-day only.
