---
title: ADR — Autonomous Feedback Loops (Closing the Intelligence Gap)
category: decisions
tags: [ADR, knowledge-graph, insights, lead-generation, retell-llm, tags]
sources: [infranodus/ontology.md]
updated: 2026-04-12
---

# ADR: Autonomous Feedback Loops

**Date:** 2026-04-12
**Status:** Accepted

## Context (Knowledge Graph Insight)
An analysis of the `omni-vault` ontology revealed two major disconnected clusters:
1. **Gap A**: The `[Lead Generation Pipeline]` (Apify/Serper) is structurally disconnected from the `[Auto-Optimization Engine]` (Reinforcement Learning). Scraping configs are static, while sequence routing is dynamic.
2. **Gap C**: `[Retell AI]` nested conversation flows are disconnected from the `[Omnichannel Logic Loops]`. A voice agent might discover a prospect's budget, but that data cannot natively inform Omni's tag-based routing logic.

## Decision

We will implement two new "Feedback Loops" to bridge these structural gaps, transforming Omni from a smart sequencer into a **Self-Evolving Research & Outreach System**.

### 1. The Scraping Feedback Loop (Bridging Gap A)
The Auto-Optimization Engine will no longer just adjust `split` node weights. It will export its highest-converting profiles back to the Lead Generation Pipeline.
- **Mechanism**: When a specific `job_keywords` configuration (e.g., "React Developer") consistently hits a terminal `action_voice` node with positive sentiment, the Optimization Engine will dynamically update the Apify parameters to heavily index on those keywords, while reducing spend on low-converting keywords.

### 2. The Voice-to-Tag Bridge (Bridging Gap C)
Retell AI conversation flows will be granted a specific tool: `update_omni_lead_tags`.
- **Mechanism**: Inside the Retell sub-canvas, an AI agent can execute a webhook back to Omni during the call (e.g., if the prospect says "Send it to me on WhatsApp", the agent calls the tool with `tag: send_whatsapp`).
- **Effect**: This instantly updates the `leads.tags` array in Postgres. Because the sequence engine uses `condition_tag_exists` logic gates, the moment the call ends, the lead is immediately routed down the WhatsApp branch, completely autonomously.

## Consequences
- **Pros**: Creates a perfectly closed-loop system. The quality of leads improves automatically over time, and cross-channel routing becomes context-aware based on deep conversational data rather than just shallow webhook events (like "email opened").
- **Cons**: Requires complex data mapping between Retell's LLM tools and Omni's Postgres database, increasing the surface area for payload validation errors.

## Related Pages
- [[knowledge-graphs]]
- [[lead-generation-injection]]
- [[auto-optimization-engine]]
- [[omnichannel-logic-loops]]
- [[retell-integration]]
