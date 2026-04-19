---
title: Settings Page
category: product
tags: [settings, UI, LinkedIn, email, voice, accounts, SMTP]
sources: []
updated: 2026-04-13
---

# Settings Page

**Route:** `/settings`  
**File:** `frontend/src/pages/Settings.tsx`

Account surface for provisioning sending identities: LinkedIn accounts via Unipile, email accounts via SMTP, and Retell voice agents.

## Tab Structure

Three round-pill tab buttons: **LinkedIn Accounts** | **Email Accounts** | **Voice Agents**.  
Default active tab: `linkedin`.

## LinkedIn Accounts Tab

Lists all accounts from `GET /accounts/linkedin`.

### Table Columns

| Column | Content |
|--------|---------|
| Name | Bold account display name |
| Unipile ID | Monospaced Unipile account ID |
| Daily cap | Per-account daily invite cap (numeric) |
| Status | `Badge asStatus` (active / paused via `is_active`) |
| Actions | Test button + Remove button |

**Test button**: Calls `POST /accounts/linkedin/{id}/test`. Returns `{ ok: boolean, error?: string }`. Shows spinner (`Loader2`) while pending. Displays inline "OK" (emerald) or "Failed" (rose) result text next to the button. Also fires a toast.

**Remove button**: Calls `DELETE /accounts/linkedin/{id}`. Rose border. Invalidates the `['settings', 'linkedin']` query.

### Add LinkedIn Account Modal

Form fields:
- Unipile ID (text, required)
- Display name (text, required)
- Email (text, optional)
- Daily invite cap (number, default 20)

`POST /accounts/linkedin` with `{ unipile_id, name, email, daily_invite_cap }`.

## Email Accounts Tab

Lists all accounts from `GET /accounts/email`.

### Table Columns

| Column | Content |
|--------|---------|
| From name | Display name for outbound email |
| From email | Monospaced sender address |
| Status | `Badge asStatus` (`is_active`) |
| Created | Formatted creation date |
| — | Remove button |

### Add Email Account Modal

Form fields:
- From name
- From email
- SMTP Host
- SMTP Port (number, default 587)
- SMTP Username
- SMTP Password
- Use TLS (checkbox, default true)

`POST /accounts/email` with the full SMTP payload.

## Voice Agents Tab

Lists Retell agents from `GET /accounts/voice`.

### Table Columns

| Column | Content |
|--------|---------|
| Name | Agent display name |
| Retell agent ID | Monospaced `retell_agent_id` |
| Status | `Badge asStatus` (`is_active`) |
| — | Remove button |

### Add Voice Agent Modal

Form fields:
- Retell agent ID (text)
- Display name (text)

`POST /accounts/voice` with `{ retell_agent_id, name }`.  
Linked agents are selectable in the `action_voice` [[canvas-editor]] node via the ConfigSidebar.

## Shared AccountModal Component

All three tabs share one `AccountModal` component. The modal renders a different form section depending on `tab` prop. A "busy" spinner disables the submit button while any mutation is pending. The modal closes and toasts on success.

## Related Pages

- [[unipile-integration]]
- [[retell-integration]]
- [[canvas-editor]]
- [[campaigns]]
