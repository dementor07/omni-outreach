# Apollo.io

**Category:** Source
**v2 node:** `source.apollo` ([backend/app/nodes/sources/apollo.py](../../../backend/app/nodes/sources/apollo.py))
**Side effect:** NETWORK

## Purpose
Pull a saved Apollo search (people or companies) into Omni as `contact.created` / `company.created` events. The projector materialises them into `omni_contacts` and `omni_companies`.

## Config schema
- `saved_search_id: str` — the Apollo saved-search id the operator wants to import
- `page_size: int` (default 100, 1..200) — Apollo API page size
- `max_pages: int` (default 5, 1..50) — cap so a single execution can't drain a 50k-row search

## Credentials
Stored in `omni_connections` as `provider="apollo"`, encrypted with Fernet (see [services/credentials.py](../../../backend/app/services/credentials.py)). The node only carries an opaque `credential_ref`; the muscle handler resolves it.

## Output handles
- `default` — search dispatched (per-row events flow asynchronously through the muscle)
- `on_error` — Apollo returned 401/403/429 or the saved search was deleted

## Events emitted (by muscle, not the node)
- `contact.created` — one per person row
- `company.created` — one per company row
- `apollo.search_completed` — telemetry with total pulled

## Operator notes
- Apollo's free tier is ~50 credits/day; the node does NOT throttle — set `max_pages` conservatively.
- Saved search must be marked "shared" inside Apollo or the API returns empty.
- Email reveals consume credits even when we already have the email from another source — dedupe upstream where possible.

## Related
- [[hunter]] — alternative source for verified emails
- [[proxycurl]] — enrich LinkedIn URLs Apollo doesn't have
