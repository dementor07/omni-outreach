---
title: Channels
category: product
tags: [outreach, messaging, voice, email]
sources: []
updated: 2026-04-19
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
These channels exist in the [[canvas-editor]] palette and the [[sequential-builder]] add-button grid, and are wired through the frontend `NodeType` union and backend `NodeType` Literal — but the dispatcher has no handler yet (tasks will silently no-op):

- **SMS** (`action_sms`) — MessageCircle icon, teal colour
- **Webhook / CRM** (`action_webhook`) — Webhook icon, orange colour; intended for CRM push/Zapier triggers
- **Instagram** (`action_instagram`) — stubbed since initial canvas build
- **Telegram** (`action_telegram`) — stubbed since initial canvas build

## Shared Characteristics
All channel templates support variable interpolation (e.g., `{{first_name}}`) via the `renderer.py` service.
