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

## Tab StructureFive round-pill tab buttons: **LinkedIn Accounts** | **Email Accounts** | **Voice Agents** | **Integrations** | **Notifications**.
Default active tab: `linkedin`.

The first three tabs show provisioned sending identities (the shared `AccountModal` handles all three creation flows). The last two tabs manage configuration rather than identities, so they hide the "Add account" button and render their own creation UI.


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

## Related Pages- [[unipile-integration]]
- [[retell-integration]]
- [[canvas-editor]]
- [[campaigns]]
- [[notifier]]
- [[approvals-page]]
- [[integrations-security-architecture]]

## Integrations Tab

`IntegrationsPanel` component. Backed by:

- `GET /settings/integrations/providers` — the provider catalog (required fields per provider)
- `GET /settings/integrations` — the stored keys (masked preview only)
- `PUT /settings/integrations` — upsert a key (encrypted at rest with AES-256)
- `DELETE /settings/integrations` — remove a key
- `POST /settings/integrations/{provider}/verify` — optional live check against the provider's API

Each provider is a card showing Shield (no keys) / ShieldCheck (all keys verified) / ShieldX (present but verification failed). Fields support show/hide for the masked preview and can be swapped in place via an "Update" flow.

The encryption model and rationale live in [[integrations-security-architecture]].

## Notifications Tab

`NotificationChannelsPanel` component. This is the operator-facing surface for the global [[notifier]] fan-out table.

Backed by `GET/POST/PATCH/DELETE /settings/notification-channels`:

| Channel type | Required config | Delivery |
|--------------|-----------------|----------|
| `slack` | `webhook_url` | POST to Slack incoming webhook |
| `email` | `to` | POST to Resend using the existing `resend_api_key` env |

The panel lists all channels with name, status badge, and target preview. Each row supports:

- **Pause/Resume** — flips `is_active` via `PATCH`
- **Remove** — deletes via `DELETE`

Creation is an inline draft card (not the shared `AccountModal`), because the field shape differs per channel type. Slack and email toggle pills swap the placeholder and the second input's type between URL and email.

This tab is consumed by `action_hot_lead_alert` nodes in the [[canvas-editor]] — each node either broadcasts to every active channel or restricts delivery to a subset via `channel_ids`.
