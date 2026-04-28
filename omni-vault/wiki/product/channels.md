---
title: Channels
category: product
tags: [outreach, messaging, voice, email, sms, webhook]
sources: []
updated: 2026-04-21
---

Omni is a multi-channel platform. Every delivery-oriented action node in the [[sequence-engine]] maps to one concrete handler in the [[dispatcher]].

As of 2026-04-21 there are no remaining palette channels that are wired in UI/backend but missing in the dispatcher path. SMS and Webhook closed the last gap documented in [[stubbed-channels-policy]].

## Active Delivery Channels

| Channel | Backend Handler | Integration | Description |
| --- | --- | --- | --- |
| **LinkedIn Invite** | `_handle_linkedin_invite` | [[unipile-integration]] | Sends a connection request. The sequencer later resumes the DAG on acceptance. |
| **LinkedIn DM** | `_handle_linkedin_dm` | [[unipile-integration]] | Sends or replies in a LinkedIn chat thread. |
| **LinkedIn InMail** | `_handle_linkedin_inmail` | [[unipile-integration]] | Sends a premium InMail. |
| **LinkedIn Profile View** | `_handle_linkedin_profile_view` | [[unipile-integration]] | Triggers a profile lookup/view and populates `linkedin_distance`. |
| **WhatsApp** | `_handle_whatsapp` | [[unipile-integration]] | Sends WhatsApp messages using the Unipile attendee format. |
| **Email** | `_handle_email` | Native SMTP | Sends directly via SMTP credentials stored in `email_accounts`. |
| **SMS** | `_handle_sms` | Twilio | Posts to Twilio `Messages.json` using env-backed credentials and logs `sms_sent`. |
| **Instagram** | `_handle_instagram` | [[unipile-integration]] | Sends Instagram DM via the configured Instagram account mapping. |
| **Telegram** | `_handle_telegram` | [[unipile-integration]] | Sends Telegram DM via username/phone resolution plus configured account ID. |
| **Voice** | `_handle_voice` | [[retell-integration]] | Triggers an AI phone call in Standard or Nested Flow mode. |
| **Webhook / CRM** | `_handle_webhook` | Generic HTTP endpoint | Sends POST/PUT/PATCH with rendered payload or raw lead JSON to external CRM/automation systems. |

## Sequence Actions That Are Not Delivery Channels

These still run through queue + dispatcher, but they mutate state or emit notifications rather than contacting the lead directly.

| Action | Handler | Behaviour |
| --- | --- | --- |
| **Add Tag** | `_handle_add_tag` | Appends a tag idempotently |
| **Remove Tag** | `_handle_remove_tag` | Removes a tag from `leads.tags[]` |
| **Enrich Lead** | `_handle_enrich` | Calls a lead-source provider enrichment path and fills only missing fields |
| **Hot Lead Alert** | `_handle_hot_lead_alert` | Renders title/body against the lead + campaign and fans out to Slack/email via [[notifier]]. Optional `channel_ids` on the node restrict delivery to a subset of active destinations |
| **Human Approval** | *(not dispatched — sequencer parks the lead)* | Opens an `approvals` row and holds the lead in place; the [[approvals-page]] resolves it and the sequencer advances `approve`/`reject` |

## Shared Characteristics

- Templates render through `renderer.py`, so variables like `{{first_name}}` work across email, DMs, SMS, and webhook bodies.
- Every successful handler logs an immutable event, marks the queue row sent, and calls `sequencer.queue_next_nodes()`.
- All channels obey campaign active hours and simulation mode.
- Final failures dead-letter into the queue record rather than disappearing silently.

> **Audit gap (2026-04-28):** the `blacklists` table and `/blacklist` router exist with a working `is_blacklisted(value, entry_type)` function, but **no caller**. Neither `lead_gen.upsert_lead` (intake) nor any dispatcher handler (delivery) consults it. Blacklisted emails / domains / linkedin URLs still get scraped, queued, and contacted. Tracked as a pending fix.

## Related Pages

- [[dispatcher]]
- [[sequence-engine]]
- [[canvas-editor]]
- [[notifier]]
- [[retell-integration]]
- [[unipile-integration]]
