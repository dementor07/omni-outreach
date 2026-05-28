# Google Sheets

**Category:** Source / Sink
**v2 nodes:** `source.sheets` ([backend/app/nodes/sources/sheets.py](../../../backend/app/nodes/sources/sheets.py))
**Side effect:** NETWORK

## Purpose
Pull a sheet range into Omni as `contact.created` events, or write workflow telemetry back into a sheet tab.

## Config schema
- `spreadsheet_id: str` — Google Sheets document id (the long opaque string in the URL)
- `range: str` (default "Sheet1!A:Z") — A1 notation
- `header_row: int` (default 1) — which row holds column names
- `key_column: str` (default "email") — used for dedupe before emitting

## Credentials
Google OAuth via [services/oauth_tokens.py](../../../backend/app/services/oauth_tokens.py). The `omni_connections` row stores the refresh token (Fernet-encrypted); access tokens are refreshed per-call.

## Output handles
- `default` — sheet dispatched
- `on_error` — sheet not shared with our service account, or 404

## Events emitted
- `contact.created` — one per row, payload built from header→column mapping

## Operator notes
- The sheet must either be (a) shared with our Google OAuth user, or (b) world-readable via "anyone with the link can view". Service-account access is NOT wired yet.
- Sheets API quota: 60 reads / minute / project — bulk imports auto-chunk.

## Related
- [[apollo]], [[hunter]] — programmatic alternatives that don't require manual sheet maintenance
