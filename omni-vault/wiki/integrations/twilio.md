# Twilio

**Category:** Channel
**v2 node:** `channel.sms` ([backend/app/nodes/channels/sms.py](../../../backend/app/nodes/channels/sms.py))
**Side effect:** MUTATE

## Purpose
Send SMS via Twilio Programmable Messaging. The node publishes `message.send_requested`; the Rust muscle dials Twilio's REST API and publishes `message.sent` / `message.failed`.

## Config schema
- `from_number: str` — E.164 sender (must be a number owned in the connected Twilio account)
- `body_template: str` (1..1600) — supports `{{contact.first_name}}` etc
- `media_url: HttpUrl | None` — for MMS (US/CA only)

## Credentials
`omni_connections` row with `provider="twilio"`, stores `account_sid + auth_token`, Fernet-encrypted. **Auth token, not API key** — API keys are a separate beast and aren't wired yet.

## Output handles
- `default` — send queued
- `on_error` — invalid number, no credits, A2P 10DLC campaign not registered

## Events emitted
- `message.send_requested` (by node)
- `message.sent` / `message.failed` (by muscle)
- `message.delivered` / `message.replied` (by webhook → see [[webhook-in]])

## Operator notes
- US 10DLC: every workspace must register a Brand + Campaign before sending or Twilio silently drops. The muscle returns `A2P_NOT_REGISTERED` and surfaces in Approvals queue.
- Toll-free numbers need verification (1–3 week lead time) — UI should warn during connection setup.

## Related
- [[retell-integration]] — voice channel using a similar pattern
- [[unipile-integration]] — LinkedIn DMs share the same `message.*` projection
