---
title: Instagram & Telegram Integration
category: integrations
tags: [instagram, telegram, unipile, messaging, channels]
sources: []
updated: 2026-04-12
---

# Instagram & Telegram Integration

Currently, `action_instagram` and `action_telegram` are stubbed in the [[sequence-engine]] taxonomy and the [[canvas-editor]] palette. 

Because Omni leverages Unipile's Unified Messaging API, extending support to these channels requires minimal structural changes, but demands specific formatting for attendee identification.

## 1. Unipile Unified Abstraction

Both Instagram and Telegram utilize the exact same endpoints as LinkedIn and WhatsApp:
- `POST /api/v1/chats` (Start a new conversation)
- `POST /api/v1/chats/{chat_id}/messages` (Reply to existing)

The difference lies entirely in the `provider_id` / `attendee_id` format and the constraints imposed by Meta/Telegram.

## 2. Instagram Implementation (`_handle_instagram`)

Instagram enforces stricter anti-spam policies on unsolicited DMs.
- **Account Type**: Requires connecting a Professional Instagram account to Unipile.
- **Attendee Identifier**: The target must be specified via their Instagram username.
  - Format: Unipile resolves the username (e.g., `@johndoe`) to an internal `provider_id`. We must hit `GET /api/v1/users/{username}?account_id={ig_account_id}` first.
- **Canvas Node Data**: The `action_instagram` node config must ensure an `instagram_account_id` is assigned (mapped to a Unipile ID).
- **Edge Cases**: If the user has "Don't receive requests" enabled in privacy settings, Unipile will return a `403` or `422`. The [[dispatcher]] must catch this, mark the task as `skipped`, and add an `ig_dm_failed` tag so the [[omnichannel-logic-loops]] can route the lead to an Email fallback.

## 3. Telegram Implementation (`_handle_telegram`)

Telegram outreach is typically based on phone numbers or public usernames.
- **Account Type**: Standard Telegram account connected via QR code to Unipile.
- **Attendee Identifier**: 
  - Phone Number format: `+{country_code}{number}` (Unipile resolves this internally).
  - Username format: `@username`.
- **Canvas Node Data**: Requires a `telegram_account_id`.
- **Edge Cases**: Telegram's strict rate limits for cold messaging non-contacts require aggressive exponential backoff in the [[dispatcher]]'s `_fail_task` logic to prevent account bans.

## 4. Architectural Next Steps

1. Add `instagram_accounts` and `telegram_accounts` tables (or a unified `messaging_accounts` table with a `provider_type` enum).
2. Update `pages/Settings.tsx` to allow Unipile QR code provisioning for IG/TG.
3. Write `_handle_instagram` and `_handle_telegram` in `services/dispatcher.py` to replicate the `_handle_whatsapp` logic, applying the specific attendee resolution steps outlined above.

## Related Pages
- [[unipile-integration]]
- [[channels]]
