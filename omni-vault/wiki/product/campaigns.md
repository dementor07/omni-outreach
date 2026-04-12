---
title: Campaigns
category: product
tags: [configuration, limits, accounts]
sources: []
updated: 2026-04-12
---

# Campaigns

A campaign is the master container for a target audience and an outreach sequence.

## Configuration Constants

Stored in the `campaigns` table, configurable via the Settings tab in the frontend:
- **`sequence_mode`**: Determines if the UI renders the [[canvas-editor]] or the linear sequential builder. (Both compile to the same DAG backend).
- **`timezone`**: The operating timezone for the campaign.
- **`active_hours_start` / `active_hours_end`**: The daily execution window (e.g., 9 to 18). The [[dispatcher]] pauses tasks outside this window.
- **`daily_lead_cap`**: Max number of new leads processed per day.
- **`invite_daily_cap`**: Safety limit for LinkedIn connection requests to prevent account restrictions.
- **`simulation_mode`**: If true, the dispatcher marks tasks as sent without actually hitting external APIs.

## Account Assignment

Campaigns must have sending identities assigned to them:
- **LinkedIn Accounts**: Assigned via `campaign_linkedin_accounts` join table. The [[dispatcher]] load-balances invites across all active accounts assigned to the campaign.
- **Email & Voice**: Assigned directly at the node level in the [[canvas-editor]] (stored in `sequence_nodes.data`).

## Lead Generation
Campaigns can automatically generate leads via Apify and Serper using the `job_search_configs` linked to the campaign.
