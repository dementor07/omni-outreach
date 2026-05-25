"""Internal API for the Rust execution engine (the muscle).

The muscle never holds long-lived secrets, never queries the live schema for
content. It only:
  1. Redeems credential refs via GET /internal/credentials/{ref}
  2. Releases them via POST /internal/credentials/{ref}/release
  3. Delegates lead-gen pulls back to the control plane via POST
     /internal/lead-gen/dispatch-pull (and dispatch-csv-import)

Auth: every endpoint requires Bearer MUSCLE_SHARED_SECRET (env). The shared
secret is symmetric — issued to the muscle container at boot. It is not the
same as JWT user tokens; humans never see this header.
"""

from __future__ import annotations

import json
import logging
import secrets
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Path
from pydantic import BaseModel

from app.config import settings
from app.db import execute, fetch_one, set_request_workspace, system_scope
from app.services.encryption import decrypt, encrypt

router = APIRouter()
log = logging.getLogger(__name__)


# ── Auth helper ──────────────────────────────────────────────────────────────


def _muscle_secret() -> str:
    return getattr(settings, "muscle_shared_secret", "") or ""


def require_muscle(authorization: str = Header(..., alias="Authorization")) -> None:
    expected = _muscle_secret()
    if not expected:
        raise HTTPException(status_code=503, detail="muscle shared secret not configured")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer")
    if authorization.removeprefix("Bearer ").strip() != expected:
        raise HTTPException(status_code=401, detail="invalid muscle secret")


# ── Credentials ──────────────────────────────────────────────────────────────


CREDENTIAL_TTL_SECONDS = 600  # 10 minutes — covers slow retries + handler latency


async def mint_credential_ref(channel: str, bundle: dict) -> str:
    """Called by the sequencer when building an ActionCommand. Persists an
    encrypted bundle and returns the opaque ref the muscle will redeem.
    """
    ref = secrets.token_urlsafe(24)
    encrypted = encrypt(json.dumps(bundle, separators=(",", ":")))
    expires_at = datetime.now(UTC) + timedelta(seconds=CREDENTIAL_TTL_SECONDS)
    await execute(
        """
        INSERT INTO credential_refs (ref, channel, bundle_encrypted, expires_at)
        VALUES ($1, $2, $3, $4)
        """,
        ref,
        channel,
        encrypted,
        expires_at,
    )
    return ref


@router.get("/credentials/{ref}", dependencies=[Depends(require_muscle)])
async def redeem_credential(ref: str = Path(..., min_length=8, max_length=128)) -> dict:
    # credential_refs is an operational table (not workspace-scoped) — the
    # muscle authenticates with the shared secret, no JWT, so we run under
    # system_scope to satisfy acquire()'s tenant binding requirement.
    async with system_scope():
        row = await fetch_one(
            "SELECT channel, bundle_encrypted, expires_at, released_at FROM credential_refs WHERE ref=$1",
            ref,
        )
        if not row:
            raise HTTPException(status_code=404, detail="credential ref not found")
        if row["released_at"]:
            raise HTTPException(status_code=410, detail="credential ref already released")
        if row["expires_at"] < datetime.now(UTC):
            raise HTTPException(status_code=410, detail="credential ref expired")

        try:
            bundle = json.loads(decrypt(row["bundle_encrypted"]))
        except Exception as e:  # noqa: BLE001
            log.error(f"[internal] credential decrypt failed for ref={ref[:8]}…: {e}")
            raise HTTPException(status_code=500, detail="credential decode failed") from e

        await execute(
            "UPDATE credential_refs SET redeemed_at = COALESCE(redeemed_at, NOW()) WHERE ref=$1",
            ref,
        )
    return bundle


@router.post("/credentials/{ref}/release", dependencies=[Depends(require_muscle)])
async def release_credential(ref: str = Path(..., min_length=8, max_length=128)) -> dict:
    async with system_scope():
        await execute(
            "UPDATE credential_refs SET released_at = NOW() WHERE ref=$1 AND released_at IS NULL",
            ref,
        )
    return {"status": "released"}


# ── Lead-gen delegation ──────────────────────────────────────────────────────


class LeadGenDispatchBody(BaseModel):
    command_id: uuid.UUID
    task_id: uuid.UUID
    lead_id: uuid.UUID
    campaign_id: uuid.UUID
    node_id: str | None = None
    payload: dict = {}


@router.post("/lead-gen/dispatch-pull", dependencies=[Depends(require_muscle)])
async def dispatch_pull(body: LeadGenDispatchBody = Body(...)) -> dict:
    """Run the lead-gen pull synchronously enough to give Rust a fired/empty/
    cooldown verdict it can push downstream. Mirrors the LeadGenPullHandler
    in dispatcher.py but is invoked by the muscle, not the legacy queue loop.

    Muscle authenticates with the shared secret (no JWT), so we look up the
    campaign's workspace and bind it for the duration of the request — every
    tenant-scoped query underneath then runs against the right slice.
    """
    from app.services import lead_gen
    from app.services.sequencer import claim_race_winner_if_applicable  # noqa: F401

    # Bind the campaign's workspace for the rest of the request.
    async with system_scope():
        camp = await fetch_one(
            "SELECT workspace_id FROM campaigns WHERE id=$1", body.campaign_id
        )
    if not camp:
        return {"status": "on_error", "error": "campaign not found"}
    set_request_workspace(str(camp["workspace_id"]))

    node_id = body.node_id
    if not node_id:
        return {"status": "on_error", "error": "node_id missing"}
    node = await fetch_one("SELECT data FROM sequence_nodes WHERE id=$1", node_id)
    d = (node.get("data") or {}) if node else (body.payload or {})
    config_id = d.get("config_id")
    cooldown_minutes = int(d.get("cooldown_minutes", 60))
    cooldown_seconds = max(0, cooldown_minutes * 60)
    if not config_id:
        return {"status": "on_error", "error": "config_id required"}

    recent = await fetch_one(
        """
        SELECT id FROM lead_gen_pull_runs
        WHERE campaign_id=$1 AND node_id=$2
          AND fired_at >= NOW() - ($3 || ' seconds')::interval
        ORDER BY fired_at DESC LIMIT 1
        """,
        body.campaign_id, node_id, str(cooldown_seconds),
    )
    if recent:
        return {
            "status": "cooldown",
            "event_type": "lead_gen_pull_skipped_cooldown",
            "telemetry": {"cooldown_minutes": cooldown_minutes},
            "metadata_overrides": {"next_handle": "cooldown"},
        }

    try:
        await lead_gen.run_lead_gen(
            campaign_id=str(body.campaign_id),
            config_id=str(config_id),
            triggered_by="muscle",
        )
    except RuntimeError as e:
        return {"status": "on_error", "error": str(e)[:300], "metadata_overrides": {"next_handle": "on_error"}}

    run = await fetch_one(
        "SELECT id, leads_added FROM lead_gen_runs WHERE config_id=$1 "
        "ORDER BY started_at DESC LIMIT 1",
        config_id,
    )
    leads_added = int(run["leads_added"]) if run and run.get("leads_added") is not None else 0
    await execute(
        """
        INSERT INTO lead_gen_pull_runs
          (campaign_id, node_id, config_id, lead_gen_run_id, triggered_by_lead_id, cooldown_seconds, fired_at)
        VALUES ($1, $2, $3, $4, $5, $6, NOW())
        """,
        body.campaign_id, node_id, config_id,
        run["id"] if run else None, body.lead_id, cooldown_seconds,
    )
    handle = "fired" if leads_added > 0 else "empty"
    return {
        "status": handle,
        "event_type": "lead_gen_pull_fired" if leads_added > 0 else "lead_gen_pull_empty",
        "telemetry": {"leads_added": leads_added, "config_id": str(config_id)},
        "metadata_overrides": {"next_handle": handle},
    }


@router.post("/lead-gen/dispatch-csv-import", dependencies=[Depends(require_muscle)])
async def dispatch_csv_import(body: LeadGenDispatchBody = Body(...)) -> dict:
    """CSV-URL pull delegated from the muscle. Mirrors CsvImportHandler.

    Same workspace-binding pattern as dispatch_pull — see that handler.
    """
    import csv as _csv
    import io as _io

    import httpx as _httpx

    from app.services import lead_gen
    from app.services.lead_sources.base import RawLead

    async with system_scope():
        camp = await fetch_one(
            "SELECT workspace_id FROM campaigns WHERE id=$1", body.campaign_id
        )
    if not camp:
        return {"status": "on_error", "error": "campaign not found"}
    set_request_workspace(str(camp["workspace_id"]))

    node_id = body.node_id
    if not node_id:
        return {"status": "on_error", "error": "node_id missing"}
    node = await fetch_one("SELECT data FROM sequence_nodes WHERE id=$1", node_id)
    d = (node.get("data") or {}) if node else (body.payload or {})
    csv_url = str(d.get("csv_url", "")).strip()
    cooldown_minutes = int(d.get("cooldown_minutes", 60))
    cooldown_seconds = max(0, cooldown_minutes * 60)
    if not csv_url:
        return {"status": "on_error", "error": "csv_url required"}

    recent = await fetch_one(
        "SELECT fired_at FROM lead_gen_pull_runs "
        "WHERE campaign_id=$1 AND node_id=$2 AND fired_at >= NOW() - ($3 || ' seconds')::interval "
        "ORDER BY fired_at DESC LIMIT 1",
        body.campaign_id, node_id, str(cooldown_seconds),
    )
    if recent:
        return {"status": "cooldown", "metadata_overrides": {"next_handle": "cooldown"}}

    async with _httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        r = await client.get(csv_url)
    if r.status_code >= 400:
        return {"status": "on_error", "error": f"csv HTTP {r.status_code}"}

    reader = _csv.DictReader(_io.StringIO(r.text))
    added = 0
    for row in reader:
        email = (row.get("email") or row.get("Email") or "").strip()
        li = (row.get("linkedin_url") or row.get("LinkedIn") or row.get("linkedin") or "").strip()
        if not email and not li:
            continue
        raw = RawLead(
            first_name=(row.get("first_name") or row.get("First Name") or "").strip(),
            last_name=(row.get("last_name") or row.get("Last Name") or "").strip(),
            email=email or None,
            linkedin_url=li or None,
            phone=(row.get("phone") or "").strip() or None,
            company=(row.get("company") or row.get("Company") or "").strip(),
            headline=(row.get("headline") or row.get("Title") or "").strip(),
        )
        inserted = await lead_gen.upsert_lead(str(body.campaign_id), raw, "csv_import")
        if inserted:
            added += 1

    await execute(
        "INSERT INTO lead_gen_pull_runs (campaign_id, node_id, cooldown_seconds, fired_at) "
        "VALUES ($1, $2, $3, NOW())",
        body.campaign_id, node_id, cooldown_seconds,
    )
    handle = "fired" if added > 0 else "empty"
    return {
        "status": handle,
        "event_type": "csv_import_done",
        "telemetry": {"added": added, "csv_url": csv_url[:200]},
        "metadata_overrides": {"next_handle": handle},
    }


# ── Sweep — drop expired credential refs ─────────────────────────────────────


async def sweep_expired_credentials() -> int:
    """Called by the worker cron. Hard-deletes released or expired rows so
    the table stays small (TTL is 10 min; in practice rows live <1s).

    credential_refs is operational, not workspace-scoped — system_scope
    satisfies acquire()'s tenant binding requirement.
    """
    async with system_scope():
        row = await fetch_one(
            """
            WITH deleted AS (
              DELETE FROM credential_refs
              WHERE released_at IS NOT NULL
                 OR expires_at < NOW() - INTERVAL '1 hour'
              RETURNING ref
            )
            SELECT COUNT(*) AS n FROM deleted
            """,
        )
    return int(row["n"]) if row else 0
