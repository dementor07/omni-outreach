---
title: Parity Gap Analysis — May 2026
category: architecture
tags: [audit, parity, design-preview, gaps]
updated: 2026-05-16
related: [[audit-2026-05-16]], [[mandate-frontend-refactor]], [[mandate-backend-reform]], [[canvas-rose-redesign]]
---

# Parity Gap Analysis — May 2026

Identifies systemic technical gaps between the current backend architecture and the structural requirements of the **omni-design-preview** prototype that drove the [[canvas-rose-redesign|rose redesign]]. Pairs with [[audit-2026-05-16]] for the broader audit context.

---

## 1. Reporting & Telemetry Gaps

### [GAP] Fragmented Campaign Metrics
- **Current**: Data is split between `/campaigns/{id}/stats` (basic counts) and `/analytics/{id}` (deep event analysis).
- **Parity Requirement**: The prototype expects a consolidated "Pulse" object.
- **Structural Need**: Create a `/campaigns/{id}/consolidated` endpoint that aggregates funnel counts, channel-specific success rates, and the last 5 activity log entries in a single response to minimize frontend waterfalls.

### [GAP] Funnel Data Integrity
- **Current**: `list_leads` uses the `leads` table status, while the dashboard often counts raw `events`.
- **Parity Requirement**: "Mission Control" needs 100% sync between the chart and the lead list.
- **Structural Need**: Standardize all reporting to derive from the `events` table (Single Source of Truth) rather than the ephemeral `status` column in `leads`.

---

## 2. Form & Settings Standardization

### [GAP] Hardcoded Configuration Forms
- **Current**: The frontend hardcodes input fields for every lead source (Apollo, Apify, etc.).
- **Parity Requirement**: The prototype uses a standardized, clean form layer.
- **Structural Need**: Implement a **JSON Schema** response in the `lead_gen/sources` registry. The backend should describe the *shape* of the config required, allowing the frontend to render consistent `Input`, `Select`, and `Toggle` components dynamically.

### [GAP] Settings Complexity
- **Current**: Integration keys are managed one-by-one.
- **Parity Requirement**: The prototype groups integrations by "Category" (Discovery, Delivery, Enrichment).
- **Structural Need**: Update the `PROVIDERS` registry in `settings.py` to include a `category` metadata field for easier UI grouping.

---

## 3. Navigation & UX Consistency

### [GAP] Breadcrumb Static Mapping
- **Current**: The `Topbar` uses a hardcoded `ROUTE_LABELS` map.
- **Parity Requirement**: Dynamic breadcrumbs (e.g., "Campaigns / **Q2 Growth Campaign** / Sequence").
- **Structural Need**: The frontend breadcrumb component needs a way to resolve UUIDs to names.
- **Solution**: A lightweight `/search/resolve?id=...` endpoint or ensuring the `Topbar` can pull the current entity name from the global state/API response.

---

## 4. Performance & Scale

### [GAP] Worker Concurrency
- **Current**: `max_jobs = 1`.
- **Parity Requirement**: Instantaneous "Real-time" dashboard feeling.
- **Structural Need**: Parallelize the arq worker to allow lead-gen scraping and outreach dispatching to run concurrently without blocking.
