# Slack

**Category:** Channel (internal notifications)
**v2 node:** `channel.slack` ([backend/app/nodes/channels/slack.py](../../../backend/app/nodes/channels/slack.py))
**Side effect:** MUTATE

## Purpose
Post to a Slack channel from inside a workflow — usually "lead replied", "deal moved", or "approval needed" alerts to the SDR team. Not a customer-facing channel.

## Config schema
- `channel: str` — `#sales-alerts` or channel id
- `text_template: str` — supports `{{contact.first_name}}`, `{{deal.stage}}` etc
- `blocks_json: str | None` — raw Block Kit payload for richer messages

## Credentials
`omni_connections` row with `provider="slack"`, stores a bot token (`xoxb-…`), Fernet-encrypted. Bot must be invited to the target channel.

## Output handles
- `default` — posted
- `on_error` — channel_not_found, not_in_channel, invalid_blocks

## Events emitted
- `slack.message_posted` — telemetry only; no projection

## Operator notes
- Use `flow.human_approval` ([backend/app/nodes/flow/human_approval.py](../../../backend/app/nodes/flow/human_approval.py)) when the team needs to react, not just be notified — Slack alerts are fire-and-forget.

## Related
- [[unipile-integration]], [[twilio]] — customer-facing channels
