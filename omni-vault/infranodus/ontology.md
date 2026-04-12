# OmniOutreach Ontology Graph

This document serves as the living knowledge graph and ontology for the OmniOutreach project, maintained for structural gap analysis and insight generation.

## Entities and Clusters

### 1. Orchestration Cluster
- **Sequence Engine (Event-Driven State Machine)**
- **Dispatcher (Pessimistic Locking Worker)**
- **Omnichannel Logic Loops (Tag-Based Routing)**

### 2. Integration Cluster
- **Unipile (LinkedIn, WhatsApp, IG, Telegram)**
- **Retell AI (Standard vs Nested Flow Voice Calls)**
- **Native SMTP (Email Delivery)**

### 3. Scalability & Intelligence Cluster
- **Event Bus (Redis Streams / Kafka for Webhooks)**
- **Auto-Optimization Engine (Reinforcement Learning / Multi-Armed Bandit)**

### 4. Top-of-Funnel Cluster
- **Lead Generation Pipeline (Apify Scrapers + Serper Enrichment)**

### 5. UI/UX Cluster
- **Canvas Editor (ReactFlow Nodal Graph)**
- **Voice Node Sub-Canvas (Macro-to-Micro Editor)**

---

## Known Edges (Existing Relationships)
- [Sequence Engine] -> sends tasks to -> [Dispatcher]
- [Unipile] -> sends webhooks to -> [Event Bus]
- [Event Bus] -> wakes parked leads in -> [Sequence Engine]
- [Auto-Optimization Engine] -> adjusts edge weights in -> [Sequence Engine]
- [Lead Generation Pipeline] -> injects leads into -> [Sequence Engine]
- [Canvas Editor] -> compiles visual graph into -> [Sequence Engine]
- [Canvas Editor] -> configures -> [Unipile] & [Retell AI]

---

## Gap Analysis (Discovered 2026-04-12)
1. **Gap A**: `[Lead Generation Pipeline]` has no inbound edges from `[Auto-Optimization Engine]`. The scraping is autonomous but "dumb" (static keywords).
2. **Gap B**: `[Event Bus]` has no outbound edges to `[Canvas Editor]`. The massive throughput of events is invisible to the operator.
3. **Gap C**: `[Retell AI (Nested Flow)]` has no state-sharing mechanism back to `[Omnichannel Logic Loops]`. If a nested Retell flow discovers a new piece of data (e.g., prospect budget), it cannot natively tag the lead for Omni's broader routing.