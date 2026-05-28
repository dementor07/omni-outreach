# Product Hunt

**Category:** Source
**v2 node:** `source.producthunt` ([backend/app/nodes/sources/producthunt.py](../../../backend/app/nodes/sources/producthunt.py))
**Side effect:** NETWORK

## Purpose
Watch a topic/maker/upvoter stream on Product Hunt and turn launches + commenters into leads. Useful for SDR sequences targeting "people who just launched".

## Config schema
- `mode: Literal["topic", "maker", "upvoters"]`
- `topic_slug: str | None` — e.g. "developer-tools"
- `lookback_hours: int` (default 24, 1..168) — how far back to scan
- `min_upvotes: int` (default 50)

## Credentials
`omni_connections` row with `provider="producthunt"`, OAuth2 dev token + API key + secret, all Fernet-encrypted. **Rotate any prior plaintext copies** (see [[../../security/rotation-checklist]] if it exists).

## Output handles
- `default` — scan dispatched
- `on_error` — 401 (token expired) or 429

## Events emitted
- `contact.created` — per maker / commenter (LinkedIn URL when PH exposes it)
- `producthunt.launch_observed` — telemetry, includes product url + tagline (good signal for personalised opener)

## Operator notes
- PH's GraphQL API is not officially rate-limited but they throttle abusers manually — keep `lookback_hours` reasonable.
- "Upvoters" mode is gated to verified makers; most workspaces will get 403.

## Related
- [[apollo]] — broader B2B sourcing
