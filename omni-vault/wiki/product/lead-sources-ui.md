---
title: Lead Sources UI
category: product
tags: [lead-gen, sources, scheduling, campaigns, configs]
sources: []
updated: 2026-04-21
---

# Lead Sources UI

`frontend/src/pages/LeadSources.tsx`

The Lead Sources page is the main product surface for "how leads get IN". It owns provider discovery, per-campaign source configs, schedule control, and run history. The [[canvas-editor]] then owns what happens after the lead enters the graph.

## Route and Purpose

- Route: `/lead-sources`
- Sidebar label: **Lead Sources** with Database icon
- Primary use case: configure multi-source intake per campaign without mixing it into the sequence-builder UX

## Page Layout

### Header

- Title and one-line description
- **New Config** button
- The button stays disabled until a campaign is selected

### Sources Overview Grid

Top-of-page availability grid populated from `GET /lead-gen/sources`.

Each card shows:

- provider display name
- short description
- availability state
- `Needs API key` hint when the provider is not configured

Current registry-backed providers include Apify Jobs, Apollo, Hunter, ProxyCurl, and GitHub.

### Campaign Selector

Single campaign dropdown. All config CRUD and run history below the selector are scoped to the currently selected campaign.

## Create Config Flow

`CreateConfigModal` is schema-driven.

- Provider-specific forms are generated from each source's `config_schema()`.
- Supports text inputs, booleans, enums, integer inputs, comma-separated arrays, and checkbox multi-select arrays.
- Posts to `POST /lead-gen/configs` with:
  - `campaign_id`
  - `source_type`
  - `config`
  - optional `label`

This keeps the UI generic while letting each provider define its own shape.

## Config Cards

Each saved config renders as a card showing:

- label or provider display name
- provider badge
- provider availability / not-configured state
- created date
- schedule badge when `cron_schedule` is set
- actions: expand, delete, run

Expanded state reveals two additional surfaces:

### Schedule Control

Backed by `PATCH /lead-gen/configs/{id}` and `cron_schedule`.

Preset dropdown values:

- Manual only
- Every hour
- Every 6 hours
- Daily at 9am
- Weekdays 9am
- Weekly (Mon 9am)

If `last_run_at` exists, the card also shows the last execution timestamp.

### Run History

Per-config history table from `GET /lead-gen/runs?config_id=...` with:

- status badge (`pending`, `running`, `done`, `failed`)
- leads found / leads added counts
- started timestamp
- error text when failed

## Manual Trigger Flow

The **Run** button posts to `POST /lead-gen/trigger` with the selected `campaign_id` and `config_id`.

- Optimistic loading state is per config card
- success toast shows provider name
- failures surface backend `detail` messages when available

## Relationship to Campaign Detail

The Lead Sources page is the full admin surface. Campaign detail now includes a lighter in-context mirror:

- `trigger_start` badge on the [[canvas-editor]] shows how many lead sources feed the campaign
- Campaign **Sources** tab shows configs, schedules, recent runs, and `Run now` without leaving the campaign workspace

Together, these two surfaces link intake and execution without duplicating the entire page inside the campaign detail view.

## Legacy Relationship

The older [[job-search-ui]] remains available for backward compatibility, but the main lead-intake product direction now runs through this page and the provider registry documented in [[multi-source-lead-gen]].

## Related Pages

- [[campaigns]]
- [[canvas-editor]]
- [[sequence-engine]]
- [[multi-source-lead-gen]]
- [[job-search-ui]]