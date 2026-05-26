"""CSV lead source node.

Reads a CSV from an operator-supplied URL and emits one ``contact.created``
event per row. The canvas runtime appends those events; downstream nodes
pick the new leads up via the events stream.
"""

from __future__ import annotations

import csv
import io
import logging
import uuid

import httpx
from pydantic import BaseModel, Field, HttpUrl

from app.nodes import (
    NodeCategory,
    NodeContext,
    NodeHandle,
    NodeManifest,
    NodeResult,
    SideEffect,
    register,
)

log = logging.getLogger(__name__)


class CsvSourceConfig(BaseModel):
    csv_url: HttpUrl = Field(description="HTTP(S) URL of a CSV file with one lead per row")
    timeout_seconds: int = Field(30, ge=1, le=120, description="HTTP timeout for the CSV fetch")


MANIFEST = NodeManifest(
    type="source.csv",
    category=NodeCategory.SOURCE,
    summary="Pull leads from a CSV URL (one row = one contact)",
    config_schema=CsvSourceConfig,
    output_handles=(
        NodeHandle("default", "Emitted once per successful pull, with the lead count in telemetry"),
        NodeHandle("empty", "Emitted when the CSV had zero usable rows"),
    ),
    side_effect=SideEffect.NETWORK,
    icon="csv",
)


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = CsvSourceConfig(**ctx.config)
    async with httpx.AsyncClient(timeout=cfg.timeout_seconds, follow_redirects=True) as client:
        resp = await client.get(str(cfg.csv_url))
    if resp.status_code >= 400:
        return NodeResult(handle="default", error=f"CSV_HTTP_{resp.status_code}")

    reader = csv.DictReader(io.StringIO(resp.text))
    events: list[dict] = []
    for row in reader:
        email = (row.get("email") or row.get("Email") or "").strip().lower()
        li = (row.get("linkedin_url") or row.get("LinkedIn") or row.get("linkedin") or "").strip()
        if not email and not li:
            continue
        contact_id = str(uuid.uuid4())
        events.append(
            {
                "event_type": "contact.created",
                "entity_type": "contact",
                "entity_id": contact_id,
                "payload": {
                    "email": email or None,
                    "linkedin_url": li or None,
                    "first_name": (row.get("first_name") or row.get("First Name") or "").strip() or None,
                    "last_name": (row.get("last_name") or row.get("Last Name") or "").strip() or None,
                    "company": (row.get("company") or row.get("Company") or "").strip() or None,
                    "headline": (row.get("headline") or row.get("Title") or "").strip() or None,
                    "phone": (row.get("phone") or "").strip() or None,
                    "source": "csv",
                },
            }
        )

    handle = "default" if events else "empty"
    return NodeResult(handle=handle, events=events, telemetry={"contacts_added": len(events), "csv_url": str(cfg.csv_url)})


register(MANIFEST, execute)
