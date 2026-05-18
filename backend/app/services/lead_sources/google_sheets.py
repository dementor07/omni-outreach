"""Google Sheets lead source (OAuth, read-only).

Requires the operator to connect their Google account via the OAuth flow at
``/oauth/google/start``. The lead-gen config stores the Sheet URL (or just the
spreadsheet ID + range) plus the user_id whose credentials should be used.

We use Google's Sheets v4 REST API (``spreadsheets.values.get``) directly to
avoid pulling in the bulky google-api-python-client; access tokens are
acquired on demand via ``app.routers.oauth.get_access_token``.
"""

from __future__ import annotations

import logging
import re

import httpx

from .base import LeadSource, RawLead

log = logging.getLogger(__name__)


# Column-header aliases. The operator's sheet column names rarely match our
# canonical field names verbatim — accept anything close.
_HEADER_ALIASES: dict[str, list[str]] = {
    "first_name": ["first_name", "firstname", "first name", "given name", "first"],
    "last_name": ["last_name", "lastname", "last name", "surname", "family name", "last"],
    "email": ["email", "email address", "work email", "e-mail"],
    "linkedin_url": ["linkedin", "linkedin url", "linkedin_url", "linkedin profile", "li url"],
    "phone": ["phone", "phone number", "mobile", "cell", "telephone"],
    "company": ["company", "organization", "organisation", "employer", "company name"],
    "headline": ["headline", "title", "job title", "role", "position"],
    "location": ["location", "city", "country", "region"],
}


def _normalize_header(h: str) -> str:
    n = (h or "").strip().lower()
    for canon, aliases in _HEADER_ALIASES.items():
        if n in aliases:
            return canon
    return ""


_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9-_]+)")


def _extract_spreadsheet_id(url_or_id: str) -> str | None:
    """Accept either a full Sheets URL or a bare spreadsheet ID."""
    s = (url_or_id or "").strip()
    if not s:
        return None
    m = _SHEET_ID_RE.search(s)
    if m:
        return m.group(1)
    # Bare ID heuristic: 30+ chars, only [a-zA-Z0-9-_]
    if re.match(r"^[a-zA-Z0-9_-]{20,}$", s):
        return s
    return None


class GoogleSheetsSource(LeadSource):
    source_type = "google_sheets"
    display_name = "Google Sheets"
    description = (
        "Pull leads from a Google Sheet. Connect your Google account "
        "(read-only access), then paste the sheet URL and the cell range."
    )

    @property
    def is_available(self) -> bool:
        # Available iff the server has OAuth credentials configured. Per-user
        # connection state is checked in search().
        from app.config import settings
        return bool(settings.google_oauth_client_id and settings.google_oauth_client_secret)

    async def search(self, config: dict) -> list[RawLead]:
        sheet_id = _extract_spreadsheet_id(str(config.get("sheet_url", "")))
        if not sheet_id:
            log.warning("[google_sheets] no sheet_url / spreadsheet ID")
            return []

        rng = str(config.get("range", "Sheet1!A1:Z1000")).strip() or "Sheet1!A1:Z1000"
        user_id = config.get("connected_user_id")
        if not user_id:
            log.warning("[google_sheets] no connected_user_id in config")
            return []

        try:
            limit_raw = config.get("max_leads", 500)
            max_leads = int(limit_raw) if limit_raw is not None else 500
        except (TypeError, ValueError):
            max_leads = 500

        from app.routers.oauth import get_access_token

        access_token = await get_access_token(user_id)
        if not access_token:
            log.error(f"[google_sheets] could not get access token for user {user_id}")
            return []

        url = (
            f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
            f"/values/{httpx.QueryParams({'range': rng}) and ''}"  # placeholder, we hand-build below
        )
        # Re-do url cleanly:
        url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values/{rng}"

        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {access_token}"},
                )
            except Exception as e:  # noqa: BLE001
                log.error(f"[google_sheets] fetch failed: {e}")
                return []

        if resp.status_code >= 400:
            log.error(f"[google_sheets] HTTP {resp.status_code}: {resp.text[:200]}")
            return []

        data = resp.json()
        values = data.get("values", [])
        if not values:
            return []

        headers = [str(h or "") for h in values[0]]
        field_map = {i: _normalize_header(headers[i]) for i in range(len(headers))}

        leads: list[RawLead] = []
        for row in values[1:]:
            if len(leads) >= max_leads:
                break
            mapped: dict = {}
            extra: dict = {}
            for i, cell in enumerate(row):
                if cell is None:
                    continue
                v = str(cell).strip()
                if not v:
                    continue
                canon = field_map.get(i, "")
                if canon:
                    mapped[canon] = v
                else:
                    raw_header = headers[i].strip() if i < len(headers) else f"col_{i}"
                    if raw_header:
                        extra[raw_header] = v
            if not mapped.get("email") and not mapped.get("linkedin_url"):
                continue
            leads.append(
                RawLead(
                    first_name=mapped.get("first_name", ""),
                    last_name=mapped.get("last_name", ""),
                    email=mapped.get("email"),
                    linkedin_url=mapped.get("linkedin_url"),
                    phone=mapped.get("phone"),
                    company=mapped.get("company", ""),
                    headline=mapped.get("headline", ""),
                    location=mapped.get("location"),
                    extra=extra,
                )
            )
        log.info(f"[google_sheets] parsed {len(leads)} leads from sheet {sheet_id}")
        return leads

    def config_schema(self) -> dict:
        return {
            "properties": {
                "sheet_url": {
                    "type": "string",
                    "title": "Google Sheet URL or ID",
                    "description": "Paste the Sheet URL (https://docs.google.com/spreadsheets/d/…) or the bare ID.",
                },
                "range": {
                    "type": "string",
                    "title": "Range",
                    "default": "Sheet1!A1:Z1000",
                    "description": "A1 notation. The first row is treated as headers.",
                },
                "connected_user_id": {
                    "type": "string",
                    "title": "Connected user",
                    "description": "Set automatically when you connect your Google account. Don't edit by hand.",
                },
                "max_leads": {
                    "type": "integer",
                    "title": "Max leads per run",
                    "default": 500,
                },
            },
            "required": ["sheet_url", "connected_user_id"],
        }
