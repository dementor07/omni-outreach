---
title: Bridge Agent
category: architecture
tags: [llm, autonomous, tooling, ci-cd]
sources: [bridge.py]
updated: 2026-04-12
---

# Claude ↔ Gemini Bridge System

The Bridge (`bridge.py`) is an autonomous development loop that orchestrates collaboration between Claude (acting as Architect/Reviewer) and Gemini (acting as Implementer).

## How It Works

Run via CLI at the repo root: `python bridge.py --rounds 3 "Add feature X"`

1. **Spec Generation**: Claude reads the goal, the `.bridge_context/*.md` files, and the `omni-vault/index.md`. It generates a precise, actionable engineering task spec.
2. **Implementation**: Gemini reads the spec and the wiki index, then modifies the codebase and commits the changes.
3. **Review**: Claude reviews the `git diff` against the spec.
4. **Approval Gate**: If Claude outputs "APPROVE", the bridge appends a summary to `omni-vault/log.md` and continues to the next round. If "REJECT", the bridge reverts the git changes and feeds Claude's critique back into the next round's spec.

## Persistence
- Execution traces are saved to `.bridge_logs/round_NN_*.md`.
- Successful rounds are appended to `omni-vault/log.md`, ensuring the wiki stays synchronized with the codebase state.

## Context Injection
To provide Claude with specific knowledge for a bridge run, markdown files can be dropped into the `.bridge_context/` directory.
