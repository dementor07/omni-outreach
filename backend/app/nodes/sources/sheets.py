"""Google Sheets lead source node (SHEETS-001).

Reads a tab from a connected Google Sheet and emits one ``contact.created``
event per row — the in-process source pattern (mirrors ``source.csv``), so the
downstream canvas picks the new leads up via the events stream.

This node is what makes the Google Sheets OAuth flow (``routers/oauth.py``) a
real capability instead of a dead-end: connecting a Google account stored a
refresh token keyed by ``user_id``, but nothing consumed it. The token is
per-user; a source node only knows its ``workspace_id``. We resolve the
workspace's connected Google account by joining ``workspace_members`` →
``google_oauth_tokens`` (any member with a live token), then mint a fresh access
token via ``oauth.get_access_token`` and call the Sheets ``values`` API.

The first row is treated as a header; columns are matched case-insensitively to
the same field names ``source.csv`` accepts (email / linkedin_url / first_name /
last_name / company / headline / phone). A row needs an email OR a LinkedIn URL
to become a contact. Contact ids are derived deterministically from the natural
key (email/linkedin) so re-importing the same sheet upserts instead of
duplicating — consistent with the contact-dedup contract (uuid5).
"""

from __future__ import annotations

import logging

import httpx
from pydantic import BaseModel, Field

from app.db import fetch_one
from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)
# Reuse the ONE deterministic contact-id function (DEDUP-001) so a sheet import
# converges on the same row a discovered/CRM contact would — re-importing the
# same sheet upserts instead of duplicating people.
from app.nodes.crm.create_contact import _contact_id
from app.routers.oauth import get_access_token

log = logging.getLogger(__name__)

SHEETS_VALUES_URL = "https://sheets.googleapis.com/v4/spreadsheets/{sid}/values/{rng}"


class SheetsSourceConfig(BaseModel):
    spreadsheet_id: str = Field(
        description="The Google Sheet ID (the long token in the sheet's URL between /d/ and /edit)"
    )
    range: str = Field(
        "A:Z",
        description="A1 range to read, e.g. 'Sheet1!A:Z'. The first row is treated as the header.",
    )
    timeout_seconds: int = Field(30, ge=1, le=120, description="HTTP timeout for the Sheets fetch")


MANIFEST = NodeManifest(
    type="source.sheets",
    category=NodeCategory.SOURCE,
    summary="Import leads from a connected Google Sheet (one row = one contact)",
    config_schema=SheetsSourceConfig,
    output_handles=(
        NodeHandle("default", "Emitted once per successful import, with the lead count in telemetry"),
        NodeHandle("empty", "Emitted when the sheet had zero usable rows"),
        NodeHandle("on_error", "Emitted when Google is not connected or the Sheets fetch failed"),
    ),
    side_effect=SideEffect.NETWORK,
    icon="sheets",
)


def _norm_header(cells: list[str]) -> dict[str, int]:
    """Map a normalised header name → column index. Accepts the same aliases as
    source.csv so a sheet exported from the same template just works."""
    aliases = {
        "email": "email",
        "linkedin": "linkedin_url",
        "linkedin_url": "linkedin_url",
        "first_name": "first_name",
        "first name": "first_name",
        "last_name": "last_name",
        "last name": "last_name",
        "company": "company",
        "headline": "headline",
        "title": "headline",
        "phone": "phone",
    }
    out: dict[str, int] = {}
    for i, raw in enumerate(cells):
        key = aliases.get((raw or "").strip().lower())
        if key and key not in out:
            out[key] = i
    return out


def _cell(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


async def _resolve_access_token(workspace_id: str) -> str | None:
    """A fresh Google access token for any member of this workspace who has a
    connected Google account. None when nobody in the workspace is connected."""
    row = await fetch_one(
        """
        SELECT m.user_id
        FROM workspace_members m
        JOIN google_oauth_tokens t ON t.user_id = m.user_id
        WHERE m.workspace_id = $1
        ORDER BY t.connected_at DESC NULLS LAST
        LIMIT 1
        """,
        workspace_id,
    )
    if not row:
        return None
    return await get_access_token(str(row["user_id"]))


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = SheetsSourceConfig(**ctx.config)

    access_token = await _resolve_access_token(ctx.workspace_id)
    if not access_token:
        return NodeResult(
            handle="on_error",
            error="GOOGLE_NOT_CONNECTED — connect a Google account in Settings → Integrations",
        )

    url = SHEETS_VALUES_URL.format(sid=cfg.spreadsheet_id, rng=cfg.range)
    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {access_token}"},
                params={"majorDimension": "ROWS"},
            )
    except Exception as e:  # noqa: BLE001
        log.warning("[sheets] fetch failed for %s: %s", cfg.spreadsheet_id, e)
        return NodeResult(handle="on_error", error="SHEETS_NETWORK_ERROR")

    if resp.status_code >= 400:
        return NodeResult(handle="on_error", error=f"SHEETS_HTTP_{resp.status_code}")

    values: list[list[str]] = resp.json().get("values") or []
    if len(values) < 2:
        return NodeResult(handle="empty", telemetry={"contacts_added": 0, "spreadsheet_id": cfg.spreadsheet_id})

    header = _norm_header(values[0])
    events: list[dict] = []
    seen: set[str] = set()
    for row in values[1:]:
        email = _cell(row, header.get("email")).lower()
        linkedin = _cell(row, header.get("linkedin_url"))
        if not email and not linkedin:
            continue
        contact_id = _contact_id(ctx.workspace_id, linkedin or None, email or None)
        if contact_id in seen:  # collapse in-sheet duplicates before emitting
            continue
        seen.add(contact_id)
        events.append(
            {
                "event_type": "contact.created",
                "entity_type": "contact",
                "entity_id": contact_id,
                "payload": {
                    "email": email or None,
                    "linkedin_url": linkedin or None,
                    "first_name": _cell(row, header.get("first_name")) or None,
                    "last_name": _cell(row, header.get("last_name")) or None,
                    "company": _cell(row, header.get("company")) or None,
                    "headline": _cell(row, header.get("headline")) or None,
                    "phone": _cell(row, header.get("phone")) or None,
                    "source": "sheets",
                },
            }
        )

    handle = "default" if events else "empty"
    return NodeResult(
        handle=handle,
        events=events,
        telemetry={"contacts_added": len(events), "spreadsheet_id": cfg.spreadsheet_id},
    )


register(MANIFEST, execute)
