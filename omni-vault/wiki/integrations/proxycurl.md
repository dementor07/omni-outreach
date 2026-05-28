# Proxycurl

**Category:** Source / Enrich
**v2 node:** `source.proxycurl` ([backend/app/nodes/sources/proxycurl.py](../../../backend/app/nodes/sources/proxycurl.py))
**Side effect:** NETWORK

## Purpose
Hydrate a LinkedIn URL (person or company) into structured fields. Source-mode imports a LinkedIn search export; enrich-mode tops up an existing contact.

## Config schema
- `linkedin_url: HttpUrl | None` — single-target enrichment
- `bulk_search_id: str | None` — Proxycurl bulk job id for source-mode imports
- `include_skills: bool` (default false) — adds ~30% credit cost
- `include_experience: bool` (default true)

## Credentials
`omni_connections` row with `provider="proxycurl"`, bearer token, Fernet-encrypted.

## Output handles
- `default` — dispatched
- `on_error` — 401/403/404 (profile private)

## Events emitted
- `contact.created` (bulk) or `contact.enriched` (single)
- `company.created` when the profile carries an unknown `current_company` URL

## Operator notes
- Proxycurl credits are expensive (~$0.01/profile); cache hits last 29 days — the muscle should check `omni_contacts.linkedin_url + updated_at` before spending.
- LinkedIn detects scraping signatures from cheap providers; Proxycurl rotates but is not bulletproof — avoid pairing with our own LinkedIn outreach on the same account.

## Related
- [[unipile-integration]] — outbound LinkedIn DMs
- [[apollo]] — bulk import alternative
