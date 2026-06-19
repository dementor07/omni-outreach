"""Internal API for the Rust execution engine (the muscle).

The muscle never holds long-lived secrets and never queries the live schema
for content. Its only contract with the control plane is:

  - GET /internal/credentials/{ref}         redeem a one-shot credential bundle
  - POST /internal/credentials/{ref}/release  release the bundle when done

Auth: every endpoint requires Bearer MUSCLE_SHARED_SECRET. Symmetric, issued
to the muscle container at boot — not the JWT used by humans.

The legacy lead-gen dispatch endpoints (dispatch-pull, dispatch-csv-import)
that lived here pre-v2 are gone. In v2 the muscle never delegates back; lead
sources are nodes the muscle executes directly. See ADR 0001.
"""

from __future__ import annotations

import json
import logging
import secrets
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, Header, HTTPException, Path, Query

from app.config import settings
from app.db import execute, fetch_one, system_scope
from app.services.encryption import decrypt, encrypt

router = APIRouter()
log = logging.getLogger(__name__)


def _muscle_secret() -> str:
    return getattr(settings, "muscle_shared_secret", "") or ""


def require_muscle(authorization: str = Header(..., alias="Authorization")) -> None:
    expected = _muscle_secret()
    if not expected:
        raise HTTPException(status_code=503, detail="muscle shared secret not configured")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer")
    provided = authorization.removeprefix("Bearer ").strip()
    # SEC-002: constant-time compare so the secret can't be recovered by timing
    # the response to a byte-by-byte guess. `!=` short-circuits on first mismatch.
    if not secrets.compare_digest(provided, expected):
        raise HTTPException(status_code=401, detail="invalid muscle secret")


CREDENTIAL_TTL_SECONDS = 600


async def mint_credential_ref(channel: str, bundle: dict) -> str:
    """Persist an encrypted credential bundle and return the opaque ref."""
    ref = secrets.token_urlsafe(24)
    encrypted = encrypt(json.dumps(bundle, separators=(",", ":")))
    expires_at = datetime.now(UTC) + timedelta(seconds=CREDENTIAL_TTL_SECONDS)
    async with system_scope():
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
    """Resolve a credential ref to its decrypted bundle.

    SEC-003: this is intentionally *short-TTL, multi-read until released*, not a
    strict single-use token. A multi-step muscle handler (e.g. Apify: run →
    poll → fetch) re-reads the same ref within the TTL; enforcing true one-shot
    would break those flows. The ref stops working once it is released
    (``released_at``) or its TTL (``CREDENTIAL_TTL_SECONDS``) expires. The
    redeemed_at timestamp is recorded on first read for observability only and
    does NOT gate subsequent reads.
    """
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


@router.get("/ats/slugs", dependencies=[Depends(require_muscle)])
async def ats_slugs(
    platform: str = Query(..., min_length=1, max_length=40),
    limit: int = Query(100, ge=1, le=2000),
    offset: int = Query(0, ge=0),
) -> dict:
    """Company slugs for an ATS platform — the muscle's ATS handlers fetch these
    (then hit each ATS's public job API per slug). Global reference data: no
    workspace, no tenancy. Deterministic order so paging is stable across runs."""
    from app.services.ats import store

    slugs = await store.get_slugs(platform, limit=limit, offset=offset)
    return {"platform": platform, "count": len(slugs), "slugs": slugs}


async def sweep_expired_credentials() -> int:
    """Hard-delete released or expired credential rows. Called by whatever
    scheduler the v2 platform ends up using (the legacy arq worker is gone)."""
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
