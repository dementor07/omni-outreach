---
title: Unipile Integration
category: integrations
tags: [unipile, linkedin, whatsapp, messaging]
sources: []
updated: 2026-04-12
---

# Unipile Integration

Unipile is the unified messaging API used for LinkedIn and WhatsApp outreach.

## Base URL

`https://api37.unipile.com:16790` (stored as `UNIPILE_BASE` in `.env`)

## Auth

`X-API-KEY` header with `UNIPILE_API_KEY` from `.env`

## What It Does for Omni

| Channel | Unipile Endpoint |
|---------|-----------------|
| LinkedIn invite | Send connection request |
| LinkedIn DM | `start_chat_with_message` or send to existing thread |
| WhatsApp | `start_chat_with_message` with `{phone}@s.whatsapp.net` as attendee_id |

## Account Model

`linkedin_accounts` table: `id, unipile_id, name, email, daily_invite_cap, is_active`

Each account's `unipile_id` maps to a connected account in Unipile. The same Unipile account can have multiple channels connected (LinkedIn + WhatsApp) — WhatsApp reuses the LinkedIn account's `unipile_id` if WhatsApp is connected on that same Unipile account.

## Lead Fetching

Unipile API also used to fetch lead profile data (headline, name) to cache in `lead_full_stats.first_name`.

## Related Pages
- [[system-overview]]
- [[channels]]
- [[sequence-engine]]

### SOTA: Rust-Native Delivery
As of 2026-05-16, the delivery of Unipile messages and invitations has been migrated to the **Rust Execution Engine**. 
- **Interface**: Python emits an `ActionCommand` via the event bus.
- **Reliability**: Rust handles the HTTPS handshake and proxy rotation, ensuring zero Python overhead for long-running I/O.
