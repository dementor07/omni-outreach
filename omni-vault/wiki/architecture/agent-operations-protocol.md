---
title: Agent Operations Protocol
category: architecture
tags: [operations, karpathy-method, multi-agent, workflow]
sources: [wiki/architecture/llm-wiki-method.md, log.md]
updated: 2026-04-13
---

# Agent Operations Protocol

This protocol operationalizes the Karpathy method for simultaneous multi-agent execution (Copilot, Claude Code, Gemini) without duplication, race conditions, or context drift.

## Objective

Create one compounding memory system where:
- The vault remains canonical.
- Only one agent writes code at a time.
- All agents produce structured handoffs.
- Every session starts and ends with deterministic vault updates.

## Canonical Roles (Hard Lanes)

1. Executor lane
- Owner: one active coding agent only.
- Allowed actions: code edits, command execution, deployment actions, migrations, tests.
- Must emit implementation receipts: changed files, validation run, outcome.

2. Planner lane
- Owner: one planning/architecture agent.
- Allowed actions: requirements decomposition, dependency mapping, risk analysis, acceptance criteria.
- Must emit execution-ready plans with explicit entry/exit conditions.

3. Reviewer lane
- Owner: one adversarial reviewer agent.
- Allowed actions: bug/risk detection, test gap analysis, regression and security checks.
- Must emit ranked findings (critical/high/medium) and blocked/unblocked verdict.

## Control Rules

1. Single-writer lock
- Exactly one agent can modify repository code at any given time.
- Other agents are read-only or write only to review artifacts.

2. Canonical state files
- `omni-vault/index.md` is the map of record.
- `omni-vault/log.md` is the append-only timeline.
- `omni-vault/wiki/` stores synthesized knowledge, never transient chat dumps.

3. Decision capture
- Any non-trivial architecture/product choice must become an ADR in `wiki/decisions/`.

4. No fragmentation
- Prefer updating canonical pages over creating near-duplicate notes.
- New page creation is allowed only when concept scope cannot fit an existing node.

5. MCP-first vault access
- All agents must use the Obsidian MCP/API path as default for vault interactions.
- Filesystem reads/writes are fallback-only for MCP/API outages or endpoint limitations.
- Session reports should note when fallback mode was used and why.

## Session Template (Mandatory)

### Start-of-session

1. Read `omni-vault/index.md` and latest `omni-vault/log.md` section.
2. Restate current objective in one paragraph.
3. Assign active lanes:
- Executor:
- Planner:
- Reviewer:
4. Define completion criteria:
- Functional:
- Validation:
- Documentation:

### During session

1. Planner outputs a compact plan and risk list.
2. Reviewer pre-mortem identifies likely breakpoints and missing tests.
3. Executor performs implementation in small batches with validation after each batch.
4. Reviewer audits each completed batch before next batch starts.
5. Vault gets incremental synthesis only for durable knowledge, not every micro-step.

### End-of-session

1. Write a final outcome summary:
- What shipped
- What was verified
- What is deferred
2. Append a new dated entry to `omni-vault/log.md`.
3. Update `omni-vault/index.md` if any new page was created.
4. Update affected canonical wiki pages with final architecture/behavior deltas.

## Handoff Format (Cross-Agent)

Every handoff must use this structure:

1. Context
- Objective:
- Constraints:
- Current branch/environment:

2. State
- Completed:
- In progress:
- Blockers:

3. Evidence
- Files changed:
- Commands/tests executed:
- Observed outputs:

4. Next action
- Immediate next step:
- Owner lane:

## Done Criteria

A task is considered complete only if all are true:

1. Code/behavior change is implemented.
2. Validation has run and is reported.
3. Relevant wiki nodes are updated.
4. `log.md` has an append-only entry for the operation.
5. No unresolved critical reviewer findings remain.

## Fast Failure Conditions

Stop and re-plan immediately when any condition is met:

1. Two agents propose conflicting architecture changes.
2. Validation results contradict expected behavior.
3. Vault index or log is skipped.
4. Executor and reviewer disagree on release readiness.

## Practical Invocation Pattern

Use this command pattern at session start:

1. Planner: produce plan + risks + acceptance criteria.
2. Reviewer: produce pre-mortem + required tests.
3. Executor: implement smallest safe slice.
4. Reviewer: gate the slice.
5. Repeat until done criteria are satisfied.

This keeps throughput high while preserving a single, compounding memory artifact.
