# Anthropic (Claude)

**Category:** AI
**v2 nodes:**
- `ai.compose` ([backend/app/nodes/ai/compose.py](../../../backend/app/nodes/ai/compose.py)) — generate personalised message bodies
- `ai.classify` ([backend/app/nodes/ai/classify.py](../../../backend/app/nodes/ai/classify.py)) — label replies (positive / neutral / objection / unsubscribe)
- `ai.score` ([backend/app/nodes/ai/score.py](../../../backend/app/nodes/ai/score.py)) — lead-fit score 0–100

**Side effect:** NETWORK

## Default model
`claude-sonnet-4-6` for compose/classify, `claude-haiku-4-5-20251001` for high-volume scoring. Override per node via `model` config.

## Config schema (compose)
- `system_prompt: str` (1..4000)
- `user_template: str` (1..4000) — Jinja-style `{{contact.*}}` `{{company.*}}`
- `max_tokens: int` (default 600, 50..4096)
- `temperature: float` (default 0.7, 0..1)
- `model: str | None` — override

## Credentials
`omni_connections` row with `provider="anthropic"`, stores API key, Fernet-encrypted. Workspace-scoped; no shared key fallback (so cost is always attributable).

## Output handles
- `default` — generation dispatched
- `on_error` — 401, 429 quota, content policy block

## Events emitted
- `ai.compose_completed` — payload `{output_text, model, input_tokens, output_tokens, cost_usd}`
- `ai.classify_completed` — payload `{label, confidence}`
- `ai.score_completed` — payload `{score, reasons[]}`

## Operator notes
- Cost is computed in the muscle from token counts × per-model price table and recorded on `omni_events_archive` for billing.
- Compose nodes auto-inject a "no fake URLs, no fabricated facts" footer into the system prompt — see muscle handler.

## Related
- [[mindstudio]] — alternative AI provider (closed-source agent flows)
- [[unipile-integration]], [[twilio]] — channels that send the composed output
