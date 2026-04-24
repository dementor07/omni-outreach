---
title: Notifier
category: architecture
tags: [notifier, alerts, slack, email, notification-channels, fan-out]
sources: []
updated: 2026-04-23
---

# Notifier

`backend/app/services/notifier.py`

The notifier is Omni's alert fan-out. It turns "something happened" events inside the sequence engine into Slack pings, email alerts, or whatever channel types we add later. It is not a message queue — it is a direct synchronous fan-out to the configured destinations, with per-channel error isolation.

## Channel Types

| `channel_type` | Config keys | Transport |
|----------------|-------------|-----------|
| `slack` | `webhook_url` | POST JSON to the Slack incoming webhook |
| `email` | `to` | POST to the Resend API using the existing `resend_api_key` |

Both are stored in the `notification_channels` table with `name`, `config JSONB`, `is_active`, and `created_at`. The table is global — channels are not scoped per campaign for v1.

## Public API

```python
async def dispatch_alert(
    title: str,
    body: str,
    context: dict[str, Any] | None = None,
    channel_ids: list[str] | None = None,
) -> int
```

- `title` is the loud headline (shown as the Slack bold prefix and the email subject).
- `body` carries the detail.
- `context` becomes the Slack attachment fields (trimmed to 10 k/v pairs, empty values filtered). On email it is currently unused but reserved.
- `channel_ids=None` fans out to every active channel. Supplying a list restricts delivery — which is how `action_hot_lead_alert` nodes target a chosen subset via `node.data.channel_ids`.
- Returns the count of successful deliveries. The caller logs that count into the `events` table.

## Error isolation

The fan-out loop wraps each channel in its own `try`/`except`. A broken Slack webhook or a Resend 4xx does not stop the other channels from firing. Per-channel failures are logged with the channel ID and type for later debugging.

No retries at this layer — if a channel flaps, the next alert will try again. If we need reliability we'll move the fan-out into the queue.

## Call sites

- `dispatcher._handle_hot_lead_alert` — the only current caller. Builds `title`, `body`, and `context` from the lead and campaign, then forwards to `dispatch_alert`.
- Approvals notifications on `human_approval` creation are a planned call site (tracked in [[human-approval-and-reply-intent]]).

## Configuration surface

- `POST/GET/PATCH/DELETE /settings/notification-channels` — CRUD for the table, validated against the `channel_type` whitelist and the required config shape (`slack` needs `webhook_url`, `email` needs `to`).
- Managed via the **Notifications** tab in [[settings-page]].

## Related Pages

- [[dispatcher]]
- [[sequence-engine]]
- [[settings-page]]
- [[human-approval-and-reply-intent]]
