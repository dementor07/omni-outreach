"""Renidly job-changes lead source (RENIDLY-002).

Pulls people who JUST changed jobs from Renidly's identity graph
(``GET /api/data/v1/job-changes/search``) and emits one ``contact.created``
per person — the classic outbound trigger: someone in a new role is
re-evaluating tooling and has budget conversations ahead of them.

In-process source (the ``source.sheets`` / ``source.producthunt`` pattern):
one paginated HTTPS call per run, no muscle involvement — which also keeps it
comfortably inside Renidly's per-minute rate limit.

Live-verified item shape (each is a complete ready-made lead):
``{event_type: joined|…, title, previous_title, detected_at, effective_date,
profile_id: prsn_…, organization_id: org_…, profile_handle,
profile_first_name, profile_last_name, profile_headline, profile_url}``.

Contact ids reuse crm.create_contact's namespace + LinkedIn natural key
(DEDUP-001): a person discovered here collides/upserts with the same person
discovered anywhere else, instead of duplicating them.
"""

from __future__ import annotations

import json
import logging
import random

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
from app.nodes.crm.create_contact import _contact_id
from app.services.encryption import decrypt

log = logging.getLogger(__name__)

_JOB_CHANGES_URL = "https://renidly.com/api/data/v1/job-changes/search"


class RenidlyJobChangesConfig(BaseModel):
    connection_name: str = Field(
        min_length=1, max_length=200, description="Renidly connection (api_key)"
    )
    limit: int = Field(
        25, ge=1, le=100, description="How many recent job-change events to pull per run"
    )
    page: int = Field(
        1, ge=1, le=1000, description="Which page of the job-change feed to pull (each page is a distinct set of people)"
    )
    randomize_page: bool = Field(
        False,
        description=(
            "Sample a RANDOM page in [1, max_page] on every run instead of a fixed page, so "
            "repeated runs surface fresh people (continuous sampling / demos). Overrides `page`."
        ),
    )
    max_page: int = Field(
        20, ge=1, le=1000, description="Upper bound for randomize_page sampling (the feed is large; keep this within its real depth)"
    )
    timeout_seconds: int = Field(30, ge=1, le=120, description="HTTP timeout for the Renidly call")


MANIFEST = NodeManifest(
    type="source.renidly_job_changes",
    category=NodeCategory.SOURCE,
    display_name="Job changes (Renidly)",
    summary="Discover people who just changed jobs — the classic outbound timing trigger",
    config_schema=RenidlyJobChangesConfig,
    output_handles=(
        NodeHandle("default", "Emitted once per successful pull, with the contact count in telemetry"),
        NodeHandle("empty", "Emitted when no job-change events came back"),
        NodeHandle("on_error", "Emitted when Renidly is not connected or the call failed"),
    ),
    capabilities=("connection:renidly",),
    side_effect=SideEffect.NETWORK,
    icon="briefcase",
    primary_fields=("connection_name",),
    advanced_fields=("limit", "page", "randomize_page", "max_page", "timeout_seconds"),
)


async def _resolve_api_key(workspace_id: str, connection_name: str) -> str | None:
    """The workspace's Renidly api_key, decrypted. In-process sources resolve
    credentials directly (the sheets pattern) — there is no muscle credential_ref
    on this path."""
    row = await fetch_one(
        "SELECT credentials_encrypted FROM omni_connections "
        "WHERE workspace_id = $1 AND provider = 'renidly' AND name = $2",
        workspace_id,
        connection_name,
    )
    if not row:
        return None
    try:
        creds = json.loads(decrypt(row["credentials_encrypted"]))
    except Exception:  # noqa: BLE001 — a corrupt bundle reads as not-connected
        log.warning("[renidly_job_changes] could not decrypt the connection bundle")
        return None
    api_key = str(creds.get("api_key") or "").strip()
    return api_key or None


async def execute(ctx: NodeContext) -> NodeResult:
    cfg = RenidlyJobChangesConfig(**ctx.config)

    api_key = await _resolve_api_key(ctx.workspace_id, cfg.connection_name)
    if not api_key:
        return NodeResult(
            handle="on_error",
            error="RENIDLY_NOT_CONNECTED — connect Renidly in Settings → Integrations",
        )

    # Each `page` of the feed is a DISTINCT set of people (verified live). A fixed
    # page returns the same people every run — fine for a steady trigger, but
    # randomize_page samples a fresh page each run so repeated runs keep pulling
    # NEW contacts (continuous sampling / live demos).
    page = random.randint(1, cfg.max_page) if cfg.randomize_page else cfg.page

    try:
        async with httpx.AsyncClient(timeout=cfg.timeout_seconds) as client:
            resp = await client.get(
                _JOB_CHANGES_URL,
                headers={"X-renidly-apikey": api_key},
                params={"limit": cfg.limit, "page": page},
            )
    except Exception as e:  # noqa: BLE001
        log.warning("[renidly_job_changes] fetch failed: %s", e)
        return NodeResult(handle="on_error", error="RENIDLY_NETWORK_ERROR")

    # Renidly answers HTTP 200 even for some failures — the envelope's `success`
    # is the source of truth (live-verified; same rule as the muscle's
    # classify_renidly_envelope).
    try:
        body = resp.json() or {}
    except Exception:  # noqa: BLE001
        return NodeResult(handle="on_error", error=f"RENIDLY_BAD_RESPONSE_HTTP_{resp.status_code}")
    if not body.get("success"):
        code = str(body.get("error_code") or resp.status_code)
        log.warning("[renidly_job_changes] rejected: %s %s", code, str(body.get("message"))[:160])
        return NodeResult(handle="on_error", error=f"RENIDLY_REJECTED_{code}")

    events: list[dict] = []
    seen: set[str] = set()
    for item in body.get("data") or []:
        handle = str(item.get("profile_handle") or "").strip()
        first = str(item.get("profile_first_name") or "").strip()
        last = str(item.get("profile_last_name") or "").strip()
        if not handle or not (first or last):
            continue
        linkedin_url = str(item.get("profile_url") or "").strip() or f"https://linkedin.com/in/{handle}"
        # DEDUP-001: the CRM's own deterministic id from the LinkedIn key, so a
        # re-pull (or the same person from another source) upserts, not duplicates.
        contact_id = _contact_id(ctx.workspace_id, linkedin_url, None)
        if contact_id in seen:
            continue
        seen.add(contact_id)
        events.append(
            {
                "event_type": "contact.created",
                "entity_type": "contact",
                "entity_id": contact_id,
                "payload": {
                    "first_name": first or None,
                    "last_name": last or None,
                    "headline": str(item.get("profile_headline") or "").strip() or None,
                    "linkedin_url": linkedin_url,
                    "source": "renidly_job_changes",
                    "custom_fields": {
                        "renidly_id": str(item.get("profile_id") or "").strip() or None,
                        "renidly_company_id": str(item.get("organization_id") or "").strip() or None,
                        "job_change_event": str(item.get("event_type") or "").strip() or None,
                        "job_change_title": str(item.get("title") or "").strip() or None,
                        "job_change_previous_title": str(item.get("previous_title") or "").strip() or None,
                        "job_change_effective_date": str(item.get("effective_date") or "").strip() or None,
                    },
                },
            }
        )

    handle = "default" if events else "empty"
    return NodeResult(handle=handle, events=events, telemetry={"contacts_added": len(events)})


register(MANIFEST, execute)
