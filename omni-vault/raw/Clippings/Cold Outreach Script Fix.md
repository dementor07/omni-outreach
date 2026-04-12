---
title: "Cold Outreach Script Fix"
source: "https://chatgpt.com/c/69db52ba-60bc-8323-a4ff-a4d06c53d256"
author:
published:
created: 2026-04-12
description: "ChatGPT is your AI chatbot for everyday use. Chat with the most advanced AI to explore ideas, solve problems, and learn faster."
tags:
  - "clippings"
---
Retell Ai Cold Call Script (humanized, High-conversion)

## Retell AI Cold Call Script (Humanized, High-Conversion)

---

## CORE PRINCIPLES (READ FIRST)

- Sound slightly unsure, not polished
- Never "pitch" — just observe and nudge
- Keep sentences short and natural
- Interruptible at all times
- No buzzwords (AI, automation, platform, etc.)

---

## GREETING (Pattern Interrupt)

"Hey — quick one, I’ll keep it short… I might be wrong here, but are you doing any outbound right now?"

ALT: "Hey — this might be slightly off, but are you guys doing outbound at the moment?"

---

## IF THEY ENGAGE

"Is that actually bringing in calls consistently, or is it a bit hit or miss?"

ALT: "Does that turn into actual meetings, or is it kind of inconsistent?"

---

## PIVOT (Observation, not pitch)

"Yeah… that’s pretty common. Usually it’s not that outreach isn’t happening — it just doesn’t turn into enough actual calls."

ALT: "Right… we hear that a lot. People are doing the activity, but the number of meetings isn’t where it should be."

---

## SOFT OFFER (No "what we do")

"We’ve been fixing that for a few teams recently — just making outbound actually turn into booked calls."

ALT: "We’ve been helping a few teams smooth that out so it actually produces meetings consistently."

---

## REVEAL (Casual, non-dramatic)

"Also — just so it doesn’t sound weird later — this is actually our system running this."

---

## CLOSE (Low pressure)

"If that’s even relevant, I can loop you in with someone — or just leave it."

ALT: "Up to you — I can connect you, or I can just send something over and you can ignore it if it’s not useful."

---

## EDGE CASES

---

## NOT INTERESTED

"Yeah that’s fair — I’ll leave you alone in a sec. Just curious though… are you happy with how many calls you’re getting right now?"

IF NO: "Yeah… that’s exactly the gap I was referring to." → Return to SOFT OFFER

IF YES: "Got it — sounds like you’ve got it handled." → End call

---

## BUSY

"Got it — when’s better, later today or tomorrow?"

IF NO RESPONSE: "All good — I’ll try again another time."

---

## SKEPTICAL

"Yeah — most people we speak to already have something in place. The issue usually isn’t sending outreach — it’s that it doesn’t convert into enough meetings."

---

## ALREADY DOING WELL

"That’s solid — out of curiosity, is that from one channel or a mix?"

"Usually even then there’s a bit of leakage somewhere."

---

## HESITATION

"No pressure at all — even a few extra meetings a month usually makes a noticeable difference."

---

## EMAIL REQUEST

"Yeah, happy to — what’s the best email for you?"

---

## CONFUSED / DOESN’T UNDERSTAND

"I just mean — are you getting a steady flow of meetings from outreach right now?"

---

## HARD NO / HOSTILE

"All good — appreciate you taking the call."

---

## FLOW SUMMARY

Greeting → Engagement → Observation → Soft Offer → Reveal → Close

Fallbacks:

- Not interested → Re-open with meeting question
- Busy → Reschedule
- Skeptical → Reframe

---

## DELIVERY NOTES (CRITICAL)

- Add slight pauses: "…"
- Occasionally start with "Yeah" or "Right"
- Don’t rush sentences
- Let user interrupt
- Never stack multiple questions

---

## FINAL CHECK

If it sounds like a script, simplify it. If it sounds too clean, break it slightly. If it sounds like a salesperson, remove half the words.

The goal is not perfection. The goal is: believable.

Omni Outreach Platform - Comprehensive Architecture Document

## Omni Outreach Automation Platform

## Comprehensive Architecture Document

---

## 1\. INTRODUCTION

## 1.1 Purpose

This document defines the complete architecture of Omni — a multi-channel, event-driven outreach control plane. It is intended to guide development, scaling, and product evolution.

## 1.2 Core Thesis

Omni is not a sequencer. It is an event-driven state machine for outbound systems.

---

## 2\. SYSTEM PARADIGM SHIFT

## 2.1 From Linear Sequences → Event-Driven Graphs

Traditional tools:

- Step 1 → Step 2 → Step 3

Omni:

- Event → Decision → Action → State Transition

## 2.2 Key Abstractions

- Lead = stateful entity
- Node = state transformer
- Edge = transition rule
- Event = trigger for execution

---

## 3\. HIGH-LEVEL ARCHITECTURE

## 3.1 Layers

1. Presentation Layer (React Canvas + Builder)
2. Orchestration Layer (DAG Engine)
3. Execution Layer (Dispatcher + Workers)
4. Integration Layer (Unipile, Retell, SMTP, Apify)
5. Data Layer (PostgreSQL + Redis)

---

## 4\. CORE DOMAIN MODEL

## 4.1 Lead

Stateful object that moves through graph

Fields:

- id
- campaign\_id
- current\_node\_id
- state (active, paused, completed)
- metadata (JSONB)

## 4.2 Node

Unified structure:

{

id,

type,

subtype,

config,

position,

metadata

}

Node Types:

- trigger
- event
- action
- condition
- control
- subflow

---

## 5\. NODE TAXONOMY

## 5.1 Trigger Nodes

- Lead Created
- Manual Trigger
- API/Webhook Trigger
- Lead Source Injected

## 5.2 Event Nodes

- On Reply
- On Email Open
- On Link Click
- On Timeout
- On Call Completed

## 5.3 Action Nodes

- Send Email
- Send LinkedIn DM
- Send WhatsApp
- Start Call (Retell)
- Update Lead Field
- Add Tag

## 5.4 Condition Nodes

- If Replied
- If Tag Exists
- If Channel Used

## 5.5 Control Nodes

- Delay
- Split
- End

## 5.6 Subflow Nodes

- Encapsulated graph execution

---

## 6\. EDGE MODEL

Edge Types:

- default
- true / false
- success / failure
- timeout
- event-driven

---

## 7\. DAG EXECUTION ENGINE

## 7.1 Execution Flow

1. Node completes
2. Outgoing edges evaluated
3. Next nodes scheduled
4. Tasks pushed to queue

## 7.2 Parking System

- Leads paused at condition/event nodes
- Resumed via webhook triggers

---

## 8\. EVENT SYSTEM DESIGN

## 8.1 Event Sources

- Messaging webhooks
- Email tracking
- Call results
- Time-based triggers

## 8.2 Event Bus (Future Enhancement)

- Kafka / Redis Streams (optional upgrade)

---

## 9\. DISPATCHER & WORKERS

## 9.1 Responsibilities

- Poll queued tasks
- Execute actions
- Update lead state

## 9.2 Concurrency

- PostgreSQL FOR UPDATE SKIP LOCKED
- Horizontal scaling safe

---

## 10\. DATA MODEL (SIMPLIFIED)

Tables:

- leads
- campaigns
- sequence\_nodes
- sequence\_edges
- executions
- events

---

## 11\. SUBFLOW ARCHITECTURE

## 11.1 Purpose

Encapsulate complexity

## 11.2 Implementation

- Node references subflow\_id
- Recursive execution

---

## 12\. FRONTEND ARCHITECTURE

## 12.1 Modes

- Sequential Builder
- Canvas Mode

## 12.2 Canvas Components

- Node Renderer
- Edge Renderer
- Sidebar Config

---

## 13\. UX PRINCIPLES

- Hide complexity by default
- Progressive disclosure
- Templates over blank canvas

---

## 14\. INTEGRATIONS

## 14.1 Unipile

- Messaging abstraction

## 14.2 Retell

- Voice execution

## 14.3 SMTP

- Email delivery

## 14.4 Apify / Serper

- Lead sourcing

---

## 15\. LEAD GENERATION ARCHITECTURE

## 15.1 Trigger-Based Ingestion

- Job scrape
- Search query
- API injection

---

## 16\. SCALABILITY

## 16.1 Horizontal Scaling

- Stateless workers
- Shared DB + Redis

## 16.2 Bottlenecks

- DB contention
- webhook bursts

---

## 17\. FAILURE HANDLING

- Retry policies
- Dead letter queues

---

## 18\. SECURITY

- API key encryption
- Role-based access

---

## 19\. FUTURE DIRECTIONS

- AI decision nodes
- Auto-optimization loops
- Reinforcement learning for outreach

---

## 20\. CONCLUSION

Omni is evolving into a programmable outbound operating system.

The key is balancing power with usability.

---

(End of Document)