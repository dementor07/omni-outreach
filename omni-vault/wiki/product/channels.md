---
title: Channels
category: product
tags: [outreach, messaging, voice, email]
sources: []
updated: 2026-04-12
---

# Outreach Channels

Omni is a multi-channel platform. Every action node in the [[sequence-engine]] maps to a specific outreach channel.

## Active Channels

| Channel                   | Backend Handler                 | Integration             | Description                                                                                                 |
| ------------------------- | ------------------------------- | ----------------------- | ----------------------------------------------------------------------------------------------------------- |
| **LinkedIn Invite**       | `_handle_linkedin_invite`       | [[unipile-integration]] | Sends connection request. Sequencer automatically waits for acceptance before continuing the DAG.           |
| **LinkedIn DM**           | `_handle_linkedin_dm`           | [[unipile-integration]] | Sends a direct message. Either starts a new chat or replies to an existing thread.                          |
| **LinkedIn InMail**       | `_handle_linkedin_inmail`       | [[unipile-integration]] | Dispatches premium InMails. Bypasses connection requirements.                                               |
| **LinkedIn Profile View** | `_handle_linkedin_profile_view` | [[unipile-integration]] | Checks prospect profile, counting as a view on LinkedIn. Populates `linkedin_distance` for logic branching. |
| **WhatsApp**              | `_handle_whatsapp`              | [[unipile-integration]] | Sends WhatsApp message using the `phone@s.whatsapp.net` attendee format.                                    |
| **Email**                 | `_handle_email`                 | Native SMTP             | Bypasses third-party APIs. Uses `email_accounts` credentials to send directly via Python `smtplib`.         |
| **Voice**                 | `_handle_voice`                 | [[retell-integration]]  | Triggers an AI phone call. Supports Standard mode (`retell-llm`) or Nested Flow mode (`conversation-flow`). |

## Stubbed Channels
These channels exist in the [[canvas-editor]] palette but the dispatcher logic is pending implementation:
- **Instagram** (`action_instagram`)
- **Telegram** (`action_telegram`)

## Shared Characteristics
All channel templates support variable interpolation (e.g., `{{first_name}}`) via the `renderer.py` service.
