# MindStudio

**Category:** AI (agent flows)
**v2 node:** `ai.compose` with `provider="mindstudio"` ([backend/app/nodes/ai/compose.py](../../../backend/app/nodes/ai/compose.py))
**Side effect:** NETWORK

## Purpose
Run a pre-built MindStudio agent (their visual builder) as a single node — useful when ops has tuned a flow inside MindStudio's UI and wants it called from Omni without re-implementing in `ai.compose` prompts.

## Config schema
- `app_id: str` — MindStudio app id
- `inputs_json: str` — JSON object passed as the app's inputs (templated against the lead/contact)
- `timeout_seconds: int` (default 60, 5..300)

## Credentials
`omni_connections` row with `provider="mindstudio"`, single API key, Fernet-encrypted. **Prior plaintext key was exposed in the repo and MUST be rotated** before this provider is enabled for any production workspace.

## Output handles
- `default` — agent run dispatched
- `on_error` — 401, app deleted, app errored mid-run

## Events emitted
- `ai.compose_completed` — payload mirrors Anthropic's so downstream nodes (channel.email etc) are provider-agnostic

## Operator notes
- MindStudio doesn't expose token counts, so cost lands as an opaque per-run dollar figure from their API.
- Long-running agents (>30s) should be marked `async=true` in MindStudio and we poll — the muscle handles this transparently.

## Related
- [[anthropic]] — preferred for transparent token-level cost and streaming
