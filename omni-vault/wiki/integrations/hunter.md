# Hunter.io

**Category:** Enrich
**v2 node:** `ai.enrich` with `provider="hunter"` ([backend/app/nodes/ai/enrich.py](../../../backend/app/nodes/ai/enrich.py))
**Side effect:** NETWORK

## Purpose
Find or verify an email address for a contact using Hunter's domain-search and email-finder endpoints. Emits `contact.enriched` so the projector backfills `omni_contacts.email` + `email_verified_at`.

## Config schema
- `mode: Literal["find", "verify"]` — `find` builds an email from (first_name, last_name, domain); `verify` checks an existing one
- `min_confidence: int` (default 80, 0..100) — drop results below this score before emitting

## Credentials
`omni_connections` row with `provider="hunter"`, single API key, Fernet-encrypted.

## Output handles
- `default` — enrichment dispatched
- `on_error` — Hunter 429 or no domain on contact

## Events emitted
- `contact.enriched` — payload `{email, confidence, sources_count, verification_status}`
- `hunter.quota_low` — telemetry signal when remaining credits < 100

## Operator notes
- Hunter rate-limits on parallel requests; muscle must serialise per workspace.
- "Accept-all" domains return high confidence but bounce — combine with NeverBounce in the muscle before declaring deliverable.

## Related
- [[apollo]] — primary lead source
- [[proxycurl]] — when only a LinkedIn URL is known
