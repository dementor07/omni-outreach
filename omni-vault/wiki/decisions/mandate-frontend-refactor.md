---
title: Architectural Mandate — Frontend De-Slopping
category: architecture
tags: [refactor, frontend, technical-debt, standards]
updated: 2026-05-05
---

# Architectural Mandate: Frontend De-Slopping

The frontend implementation has devolved into "Feature Slop," characterized by monolithic components and redundant logic. This document mandates a structural overhaul.

## 1. The "Campaigns.tsx" Mega-Component
- **The Problem**: At 2,000+ lines, `Campaigns.tsx` is an unmaintainable "God Object." It handles navigation, state, canvas rendering, sequential logic, lead tables, settings, and analytics.
- **The Mandate**: Shred `Campaigns.tsx` into a modular directory structure:
  - `src/pages/Campaigns/`
    - `CampaignList.tsx` (The grid view)
    - `CampaignEditor.tsx` (The container)
    - `components/Canvas/` (ReactFlow logic)
    - `components/Sequential/` (Linear view)
    - `components/Panels/` (Settings, Sources, Analytics)
- **Goal**: No single file should exceed 300 lines. Use **Atomic Design** principles.

## 2. Redundancy: The Sequential/Canvas Split
- **The Problem**: `SequentialBuilder.tsx` is a needless addition that duplicates 80% of the logic found in the Canvas.
- **The Mandate**: Converge on a **Single Source of Truth**. The "Sequential" view should be a **layout mode** of the Canvas data, not a separate codebase. 
- **Refactor**: Build a `SequentialLayoutEngine` that renders the graph as a list. Delete the standalone `SequentialBuilder`.

## 3. "Prop-Drilling" vs Centralized State
- **The Problem**: State is currently "drilled" through dozens of layers, leading to brittle UI updates.
- **The Mandate**: Use **Zustand** or **React Query** more aggressively to manage shared campaign state. 
- **Goal**: The Sidebar should "know" which node is selected by listening to a store, not by receiving 15 props from the parent.

## 4. Visual Validation
- **The Problem**: Node "Readiness" is a hardcoded guess (check if ID exists).
- **The Mandate**: Implement a **JSON Schema Validator** for every node. A node is only "Ready" if its data payload passes a strict structural check.


### Status Update (2026-05-05) - Phase 4 Mitigation
- **Shredded the Mega-Component**: `Campaigns.tsx` has been refactored into a modular architecture under `src/pages/Campaigns/`.
- **Atomic Design**: Logic is now isolated into `Nodes`, `Edges`, `Sidebar`, and `Panels`.
- **Single Source of Truth**: Unified types and constants now drive both the Canvas and Sequential views.
