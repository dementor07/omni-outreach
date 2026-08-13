"""Durable job broker for workspace-owned external agent harnesses.

Postgres owns job state, leases, and results. Redis is an optimisation only:
it wakes held polls and exposes short-lived worker presence to the browser. A
Redis interruption can delay an idle poll until its timeout, but can neither
lose a queued job nor permit a duplicate claim.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import secrets
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import asyncpg

from app import db
from app.db import acquire, execute, fetch_all, fetch_one
from app.services.view_architect import validate_candidate_view
from app.services.view_widgets import ViewLayoutError

log = logging.getLogger(__name__)

LEASE_SECONDS = 90
MAX_POLL_SECONDS = 25
_PRESENCE_GRACE_SECONDS = 10
_PRESENCE_KEY_TTL_SECONDS = 24 * 60 * 60


class AgentHarnessError(ValueError):
    """A stable, user-actionable broker failure."""


class AgentLeaseError(AgentHarnessError):
    """The caller no longer owns a live lease for this job."""


def _lease_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _presence_key(workspace_id: str) -> str:
    return f"omni:harness:workers:{workspace_id}"


def _wake_channel(workspace_id: str) -> str:
    return f"omni:harness:jobs:{workspace_id}"


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


async def _set_presence(
    workspace_id: str,
    harness_id: str,
    state: str,
    *,
    active_until: datetime,
    job_id: UUID | str | None = None,
) -> None:
    """Best-effort ephemeral presence; never participates in correctness."""
    client = db.redis_client
    if client is None:
        return
    payload = {
        "harness_id": harness_id,
        "state": state,
        "job_id": str(job_id) if job_id else None,
        "last_seen_at": _iso(datetime.now(UTC)),
        "active_until": _iso(active_until),
    }
    try:
        key = _presence_key(workspace_id)
        async with client.pipeline(transaction=False) as pipe:
            pipe.hset(key, harness_id, json.dumps(payload, separators=(",", ":")))
            pipe.expire(key, _PRESENCE_KEY_TTL_SECONDS)
            await pipe.execute()
    except Exception:  # noqa: BLE001 -- presence must not fail a durable job operation
        log.warning("agent harness presence update failed", exc_info=True)


async def list_active_workers(workspace_id: str) -> list[dict[str, Any]]:
    client = db.redis_client
    if client is None:
        return []
    try:
        raw_workers = await client.hgetall(_presence_key(workspace_id))
    except Exception:  # noqa: BLE001
        log.warning("agent harness presence read failed", exc_info=True)
        return []

    now = datetime.now(UTC)
    active: list[dict[str, Any]] = []
    stale_fields: list[str] = []
    for field, raw in raw_workers.items():
        try:
            worker = json.loads(raw)
            until = datetime.fromisoformat(str(worker["active_until"]).replace("Z", "+00:00"))
            if until > now:
                active.append(worker)
            else:
                stale_fields.append(field)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            stale_fields.append(field)
    if stale_fields:
        try:
            await client.hdel(_presence_key(workspace_id), *stale_fields)
        except Exception:  # noqa: BLE001
            log.debug("could not prune stale harness presence", exc_info=True)
    active.sort(key=lambda worker: worker.get("last_seen_at", ""), reverse=True)
    return active


async def _signal_job(workspace_id: str, job_id: UUID | str) -> None:
    client = db.redis_client
    if client is None:
        return
    try:
        await client.publish(_wake_channel(workspace_id), str(job_id))
    except Exception:  # noqa: BLE001 -- the durable row remains claimable
        log.warning("agent harness wake publish failed", exc_info=True)


async def create_job(
    *,
    workspace_id: str,
    kind: str,
    target_type: str,
    target_id: UUID,
    target_version: datetime | None,
    payload: dict[str, Any],
    created_by: str | None,
    requested_harness_id: str | None = None,
) -> dict[str, Any]:
    """Create one open job per target; retrying the browser request is idempotent."""
    # An expired queued job may never have met a polling harness, so the claim
    # path has not had a chance to terminalize it. Do that here as well before
    # the partial unique index decides whether this is an idempotent retry.
    await execute(
        """
        UPDATE omni_agent_jobs
        SET status='expired', completed_at=NOW(), updated_at=NOW()
        WHERE kind=$1 AND target_type=$2 AND target_id=$3
          AND status IN ('queued', 'working') AND expires_at <= NOW()
        """,
        kind,
        target_type,
        target_id,
    )
    args = (
        workspace_id,
        kind,
        target_type,
        target_id,
        target_version,
        json.dumps(payload),
        created_by or None,
        requested_harness_id,
    )
    try:
        row = await fetch_one(
            """
            INSERT INTO omni_agent_jobs (
                workspace_id, kind, target_type, target_id, target_version,
                payload, created_by, requested_harness_id
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8)
            RETURNING *
            """,
            *args,
        )
    except asyncpg.UniqueViolationError:
        row = await fetch_one(
            """
            SELECT * FROM omni_agent_jobs
            WHERE kind=$1 AND target_type=$2 AND target_id=$3
              AND status IN ('queued', 'working')
            ORDER BY created_at DESC LIMIT 1
            """,
            kind,
            target_type,
            target_id,
        )
    if row is None:  # defensive: INSERT RETURNING and the conflict lookup cannot both miss
        raise AgentHarnessError("could not create or recover the agent job")
    await _signal_job(workspace_id, row["id"])
    return row


async def get_job(job_id: UUID) -> dict[str, Any] | None:
    return await fetch_one("SELECT * FROM omni_agent_jobs WHERE id=$1", job_id)


async def cancel_job(job_id: UUID) -> dict[str, Any] | None:
    return await fetch_one(
        """
        UPDATE omni_agent_jobs
        SET status='cancelled', lease_hash=NULL, lease_expires_at=NULL,
            completed_at=NOW(), updated_at=NOW()
        WHERE id=$1 AND status IN ('queued', 'working')
        RETURNING *
        """,
        job_id,
    )


async def _claim_next(workspace_id: str, harness_id: str) -> tuple[dict[str, Any], str] | None:
    """Requeue expired leases, then atomically claim the oldest queued job."""
    lease_token = f"omni_lease_{secrets.token_urlsafe(32)}"
    token_hash = _lease_hash(lease_token)
    async with acquire() as conn:
        await conn.execute(
            """
            UPDATE omni_agent_jobs
            SET status='expired', lease_hash=NULL, lease_expires_at=NULL,
                completed_at=NOW(), updated_at=NOW()
            WHERE status IN ('queued', 'working') AND expires_at <= NOW()
            """
        )
        await conn.execute(
            """
            UPDATE omni_agent_jobs
            SET status='queued', harness_id=NULL, lease_hash=NULL,
                lease_expires_at=NULL, updated_at=NOW()
            WHERE status='working' AND lease_expires_at <= NOW() AND expires_at > NOW()
            """
        )
        row = await conn.fetchrow(
            """
            WITH candidate AS (
                SELECT id
                FROM omni_agent_jobs
                WHERE status='queued' AND expires_at > NOW()
                  AND (requested_harness_id IS NULL OR requested_harness_id=$1)
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE omni_agent_jobs AS job
            SET status='working', harness_id=$1, lease_hash=$2,
                lease_expires_at=NOW() + ($3 * INTERVAL '1 second'),
                claimed_at=NOW(), last_heartbeat_at=NOW(),
                attempts=attempts + 1, updated_at=NOW()
            FROM candidate
            WHERE job.id=candidate.id
            RETURNING job.*
            """,
            harness_id,
            token_hash,
            LEASE_SECONDS,
        )
    if row is None:
        return None
    claimed = dict(row)
    await _set_presence(
        workspace_id,
        harness_id,
        "working",
        active_until=datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS),
        job_id=claimed["id"],
    )
    return claimed, lease_token


async def poll_for_job(
    workspace_id: str,
    harness_id: str,
    wait_seconds: int,
) -> tuple[dict[str, Any], str] | None:
    """Hold a reconnect-safe poll, waking on Redis and claiming from Postgres."""
    wait_seconds = max(0, min(wait_seconds, MAX_POLL_SECONDS))
    now = datetime.now(UTC)
    await _set_presence(
        workspace_id,
        harness_id,
        "listening",
        active_until=now + timedelta(seconds=wait_seconds + _PRESENCE_GRACE_SECONDS),
    )

    pubsub = None
    client = db.redis_client
    if client is not None and wait_seconds:
        try:
            # Subscribe BEFORE checking Postgres so a create between these two
            # operations cannot be missed (the durable query handles older jobs).
            pubsub = client.pubsub()
            await pubsub.subscribe(_wake_channel(workspace_id))
            # redis-py exposes the SUBSCRIBE acknowledgement as the first
            # message. Drain it now; otherwise get_message(ignore_subscribe…)
            # returns None immediately instead of holding the real job poll.
            await pubsub.get_message(ignore_subscribe_messages=True, timeout=1)
        except Exception:  # noqa: BLE001
            log.warning("agent harness wake subscription failed", exc_info=True)
            pubsub = None

    try:
        claimed = await _claim_next(workspace_id, harness_id)
        if claimed is not None or wait_seconds == 0:
            return claimed

        if pubsub is not None:
            try:
                await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=wait_seconds,
                )
            except Exception:  # noqa: BLE001
                log.warning("agent harness held poll interrupted", exc_info=True)
        else:
            # Redis is only a wake optimisation. On degradation, keep the API's
            # long-poll timing stable, then re-check the durable queue once.
            await asyncio.sleep(wait_seconds)
        return await _claim_next(workspace_id, harness_id)
    finally:
        if pubsub is not None:
            try:
                await pubsub.unsubscribe(_wake_channel(workspace_id))
                await pubsub.aclose()
            except Exception:  # noqa: BLE001
                log.debug("agent harness pubsub cleanup failed", exc_info=True)


async def heartbeat_job(
    *, workspace_id: str, job_id: UUID, harness_id: str, lease_token: str
) -> dict[str, Any]:
    row = await fetch_one(
        """
        UPDATE omni_agent_jobs
        SET lease_expires_at=NOW() + ($4 * INTERVAL '1 second'),
            last_heartbeat_at=NOW(), updated_at=NOW()
        WHERE id=$1 AND harness_id=$2 AND lease_hash=$3
          AND status='working' AND lease_expires_at > NOW()
        RETURNING *
        """,
        job_id,
        harness_id,
        _lease_hash(lease_token),
        LEASE_SECONDS,
    )
    if row is None:
        raise AgentLeaseError("lease expired, was cancelled, or belongs to another harness")
    await _set_presence(
        workspace_id,
        harness_id,
        "working",
        active_until=datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS),
        job_id=job_id,
    )
    return row


async def append_progress(
    *,
    workspace_id: str,
    job_id: UUID,
    harness_id: str,
    lease_token: str,
    message: str,
) -> dict[str, Any]:
    event = [{"at": _iso(datetime.now(UTC)), "message": message}]
    row = await fetch_one(
        """
        UPDATE omni_agent_jobs
        SET progress=(
                SELECT COALESCE(jsonb_agg(item ORDER BY ord), '[]'::jsonb)
                FROM (
                    SELECT item, ord
                    FROM jsonb_array_elements(progress || $4::jsonb)
                         WITH ORDINALITY AS events(item, ord)
                    ORDER BY ord DESC
                    LIMIT 50
                ) AS recent
            ),
            lease_expires_at=NOW() + ($5 * INTERVAL '1 second'),
            last_heartbeat_at=NOW(), updated_at=NOW()
        WHERE id=$1 AND harness_id=$2 AND lease_hash=$3
          AND status='working' AND lease_expires_at > NOW()
        RETURNING *
        """,
        job_id,
        harness_id,
        _lease_hash(lease_token),
        json.dumps(event),
        LEASE_SECONDS,
    )
    if row is None:
        raise AgentLeaseError("lease expired, was cancelled, or belongs to another harness")
    await _set_presence(
        workspace_id,
        harness_id,
        "working",
        active_until=datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS),
        job_id=job_id,
    )
    return row


def validate_result(kind: str, result: dict[str, Any]) -> dict[str, Any]:
    """One validation registry for every harness job kind."""
    if kind == "view.author":
        try:
            return validate_candidate_view(result)
        except ViewLayoutError as exc:
            raise AgentHarnessError(str(exc)) from exc
    raise AgentHarnessError(f"unsupported agent job kind: {kind}")


async def complete_job(
    *,
    workspace_id: str,
    job_id: UUID,
    harness_id: str,
    lease_token: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    owned = await fetch_one(
        """
        SELECT id, kind FROM omni_agent_jobs
        WHERE id=$1 AND harness_id=$2 AND lease_hash=$3
          AND status='working' AND lease_expires_at > NOW()
        """,
        job_id,
        harness_id,
        _lease_hash(lease_token),
    )
    if owned is None:
        raise AgentLeaseError("lease expired, was cancelled, or belongs to another harness")
    validated = validate_result(str(owned["kind"]), result)
    row = await fetch_one(
        """
        UPDATE omni_agent_jobs
        SET status='succeeded', result=$4::jsonb, lease_hash=NULL,
            lease_expires_at=NULL, completed_at=NOW(), updated_at=NOW()
        WHERE id=$1 AND harness_id=$2 AND lease_hash=$3
          AND status='working' AND lease_expires_at > NOW()
        RETURNING *
        """,
        job_id,
        harness_id,
        _lease_hash(lease_token),
        json.dumps(validated),
    )
    if row is None:
        raise AgentLeaseError("lease expired while the result was being validated")
    await _set_presence(
        workspace_id,
        harness_id,
        "waiting",
        active_until=datetime.now(UTC) + timedelta(seconds=_PRESENCE_GRACE_SECONDS),
    )
    return row


async def fail_job(
    *,
    workspace_id: str,
    job_id: UUID,
    harness_id: str,
    lease_token: str,
    error: str,
) -> dict[str, Any]:
    row = await fetch_one(
        """
        UPDATE omni_agent_jobs
        SET status='failed', error=$4, lease_hash=NULL, lease_expires_at=NULL,
            completed_at=NOW(), updated_at=NOW()
        WHERE id=$1 AND harness_id=$2 AND lease_hash=$3
          AND status='working' AND lease_expires_at > NOW()
        RETURNING *
        """,
        job_id,
        harness_id,
        _lease_hash(lease_token),
        error,
    )
    if row is None:
        raise AgentLeaseError("lease expired, was cancelled, or belongs to another harness")
    await _set_presence(
        workspace_id,
        harness_id,
        "waiting",
        active_until=datetime.now(UTC) + timedelta(seconds=_PRESENCE_GRACE_SECONDS),
    )
    return row


async def mark_applied(job_id: UUID) -> None:
    await fetch_one(
        """
        UPDATE omni_agent_jobs SET applied_at=NOW(), updated_at=NOW()
        WHERE id=$1 AND status='succeeded' AND applied_at IS NULL
        RETURNING id
        """,
        job_id,
    )


async def list_recent_jobs(limit: int = 50) -> list[dict[str, Any]]:
    return await fetch_all(
        "SELECT * FROM omni_agent_jobs ORDER BY created_at DESC LIMIT $1",
        limit,
    )
