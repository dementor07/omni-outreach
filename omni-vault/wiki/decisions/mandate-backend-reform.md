---
title: Architectural Mandate — Backend Structural Reform
category: architecture
tags: [refactor, backend, technical-debt, patterns]
updated: 2026-05-05
---

# Architectural Mandate: Backend Structural Reform

The backend is currently a "Procedural Drip" of if-else statements. To support "Core Functionality Done Right," the system must move to a **Protocol-Driven** architecture.

## 1. Sequence Engine: Strategy Pattern
- **The Problem**: `sequencer.py` uses a massive `if node_type == ...` block. This is "Slop" that makes adding new logic dangerous.
- **The Mandate**: Refactor to a **Node Strategy Registry**.
  - Define a `BaseNodeHandler` class.
  - Each node (Wait, Email, Split) should be its own class in a `nodes/` directory.
  - The Sequencer should simply look up the handler in a registry and call `.execute()`.

## 2. Data Layer: Repository Pattern
- **The Problem**: Raw SQL is scattered across routers. This makes schema changes (like the "Phone-Only Lead" fix) impossible to manage without global breakage.
- **The Mandate**: Centralize all data access into a **Repository Layer**.
  - `leads_repo.py`, `campaigns_repo.py`, etc.
  - No `fetch_all` or `execute` calls should exist inside the Routers or Sequencer. They must call the Repository methods.

## 3. Lead Identity: Contract Relaxation
- **The Problem**: Hardcoded requirement for LinkedIn/Email in `lead_gen.py`.
- **The Mandate**: Update the `RawLead` contract to support **Sparse Identity**.
  - A lead is valid if it has (Name + Phone) OR (LinkedIn) OR (Email).
  - The Sequencer must be updated to skip nodes that require missing fields (e.g., skip Email node if no email present) rather than failing the entire lead.

## 4. Instrumentation: The Activity Log
- **The Problem**: `activity_log` table is empty while system actions are "Silent."
- **The Mandate**: MANDATORY call to `log_activity` for:
  - Lead Import Success/Failure (with reasons).
  - Node Configuration Changes.
  - Campaign Start/Pause/Edit.
  - Account Authentication Errors.
