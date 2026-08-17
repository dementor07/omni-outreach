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
RUNNER_LEASE_SECONDS = LEASE_SECONDS
MAX_POLL_SECONDS = 25
_PRESENCE_GRACE_SECONDS = 10
_PRESENCE_KEY_TTL_SECONDS = 24 * 60 * 60


class AgentHarnessError(ValueError):
    """A stable, user-actionable broker failure."""


class AgentLeaseError(AgentHarnessError):
    """The caller no longer owns a live lease for this job."""


class AgentJobConflictError(AgentHarnessError):
    """A different open proposal already owns this target."""


class AgentRunnerConflictError(AgentHarnessError):
    """A different live process owns this workspace harness identity."""


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


async def worker_presence(workspace_id: str) -> dict[str, Any]:
    """Return workers plus whether the ephemeral presence store was readable.

    An unavailable Redis presence layer is intentionally different from a
    healthy, definitive empty set. Durable jobs continue to work in either
    case; this flag exists so the UI never calls an observability outage
    "offline".
    """
    client = db.redis_client
    if client is None:
        return {"available": False, "workers": []}
    try:
        raw_workers = await client.hgetall(_presence_key(workspace_id))
    except Exception:  # noqa: BLE001
        log.warning("agent harness presence read failed", exc_info=True)
        return {"available": False, "workers": []}

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
    return {"available": True, "workers": active}


async def list_active_workers(workspace_id: str) -> list[dict[str, Any]]:
    """Compatibility wrapper for older callers of the list-only contract."""
    return (await worker_presence(workspace_id))["workers"]


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
    origin: str = "harness",
) -> dict[str, Any]:
    """Create one open job per target; only an *exact* retry is idempotent."""
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
        origin,
    )
    try:
        row = await fetch_one(
            """
            INSERT INTO omni_agent_jobs (
                workspace_id, kind, target_type, target_id, target_version,
                payload, created_by, requested_harness_id, origin
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7, $8, $9)
            RETURNING *
            """,
            *args,
        )
    except asyncpg.UniqueViolationError:
        row = await fetch_one(
            """
            SELECT * FROM omni_agent_jobs
            WHERE workspace_id=$1 AND kind=$2 AND target_type=$3 AND target_id=$4
              AND status IN ('queued', 'working', 'succeeded')
              AND applied_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            workspace_id,
            kind,
            target_type,
            target_id,
        )
        if row is not None:
            existing_payload = row.get("payload")
            if isinstance(existing_payload, str):
                existing_payload = json.loads(existing_payload)
            existing_fingerprint = (
                existing_payload.get("request_fingerprint")
                if isinstance(existing_payload, dict)
                else None
            )
            requested_fingerprint = payload.get("request_fingerprint")
            same_request = (
                existing_fingerprint == requested_fingerprint
                if existing_fingerprint and requested_fingerprint
                else existing_payload == payload
            )
            exact_retry = (
                row.get("target_version") == target_version
                and same_request
                and row.get("requested_harness_id") == requested_harness_id
                and (row.get("origin") or "harness") == origin
            )
            if not exact_retry:
                raise AgentJobConflictError(
                    "a different proposal is already queued, working, or awaiting review "
                    "for this view; cancel or discard it before submitting changed instructions"
                )
    if row is None:  # defensive: INSERT RETURNING and the conflict lookup cannot both miss
        raise AgentHarnessError("could not create or recover the agent job")
    if row.get("status") == "queued":
        await _signal_job(workspace_id, row["id"])
    return row


async def create_completed_job(
    *,
    workspace_id: str,
    kind: str,
    target_type: str,
    target_id: UUID,
    target_version: datetime | None,
    payload: dict[str, Any],
    result: dict[str, Any],
    created_by: str | None,
    origin: str,
) -> dict[str, Any]:
    """Persist a synchronously authored proposal under the same review contract."""
    validated = validate_result(kind, result)
    review = await review_result(kind, payload, validated)
    if not review.get("all_queries_valid", False):
        raise AgentHarnessError("the proposal contains a query that could not be executed")
    try:
        row = await fetch_one(
            """
            INSERT INTO omni_agent_jobs (
                workspace_id, kind, target_type, target_id, target_version,
                payload, result, review, created_by, origin, status, completed_at
            )
            VALUES ($1, $2, $3, $4, $5, $6::jsonb, $7::jsonb, $8::jsonb,
                    $9, $10, 'succeeded', NOW())
            RETURNING *
            """,
            workspace_id,
            kind,
            target_type,
            target_id,
            target_version,
            json.dumps(payload),
            json.dumps(validated),
            json.dumps(review),
            created_by or None,
            origin,
        )
    except asyncpg.UniqueViolationError:
        row = await fetch_one(
            """
            SELECT * FROM omni_agent_jobs
            WHERE workspace_id=$1 AND kind=$2 AND target_type=$3 AND target_id=$4
              AND status IN ('queued', 'working', 'succeeded')
              AND applied_at IS NULL
            ORDER BY created_at DESC LIMIT 1
            """,
            workspace_id,
            kind,
            target_type,
            target_id,
        )
        existing_payload = row.get("payload") if row else None
        if isinstance(existing_payload, str):
            existing_payload = json.loads(existing_payload)
        exact_completed_retry = bool(
            row
            and row.get("status") == "succeeded"
            and row.get("target_version") == target_version
            and row.get("origin") == origin
            and isinstance(existing_payload, dict)
            and existing_payload.get("request_fingerprint")
            == payload.get("request_fingerprint")
        )
        if not exact_completed_retry:
            raise AgentJobConflictError(
                "a different proposal is already queued, working, or awaiting review "
                "for this view; cancel or discard it before generating another"
            )
    if row is None:
        raise AgentHarnessError("could not persist the authored proposal")
    return row


async def _reconcile_stale_jobs(job_id: UUID | None = None) -> None:
    target = " AND id=$1" if job_id is not None else ""
    args: tuple[Any, ...] = (job_id,) if job_id is not None else ()
    await execute(
        """
        UPDATE omni_agent_jobs
        SET status='expired', lease_hash=NULL, lease_expires_at=NULL,
            completed_at=NOW(), updated_at=NOW()
        WHERE status IN ('queued', 'working') AND expires_at <= NOW()
        """ + target,
        *args,
    )
    await execute(
        """
        UPDATE omni_agent_jobs
        SET status='queued', harness_id=NULL, lease_hash=NULL,
            lease_expires_at=NULL, updated_at=NOW()
        WHERE status='working' AND lease_expires_at <= NOW() AND expires_at > NOW()
        """ + target,
        *args,
    )


async def get_job(job_id: UUID) -> dict[str, Any] | None:
    await _reconcile_stale_jobs(job_id)
    return await fetch_one("SELECT * FROM omni_agent_jobs WHERE id=$1", job_id)


async def get_open_job_for_target(
    *,
    kind: str,
    target_type: str,
    target_id: UUID,
) -> dict[str, Any] | None:
    """Return the target's one durable open proposal, independent of recency."""
    await _reconcile_stale_jobs()
    return await fetch_one(
        """
        SELECT * FROM omni_agent_jobs
        WHERE kind=$1 AND target_type=$2 AND target_id=$3
          AND status IN ('queued', 'working', 'succeeded')
          AND applied_at IS NULL
        ORDER BY created_at DESC
        LIMIT 1
        """,
        kind,
        target_type,
        target_id,
    )


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


async def discard_proposal(job_id: UUID) -> dict[str, Any] | None:
    """Close one unapplied succeeded proposal without changing its target."""
    return await fetch_one(
        """
        UPDATE omni_agent_jobs
        SET status='cancelled', completed_at=COALESCE(completed_at, NOW()), updated_at=NOW()
        WHERE id=$1 AND status='succeeded' AND applied_at IS NULL
        RETURNING *
        """,
        job_id,
    )


async def _renew_runner_ownership(
    workspace_id: str,
    harness_id: str,
    runner_id: UUID,
) -> dict[str, Any]:
    """Acquire or renew one durable runner lease for a workspace harness.

    The upsert is the cross-process correctness boundary. A reconnect carrying
    the same private runner UUID renews immediately; a different process may
    take over only after both the runner lease and any active job lease ended.
    """
    row = await fetch_one(
        """
        INSERT INTO omni_agent_runners (
            workspace_id, harness_id, runner_id, lease_expires_at
        )
        VALUES ($1, $2, $3, NOW() + ($4 * INTERVAL '1 second'))
        ON CONFLICT (workspace_id, harness_id) DO UPDATE
        SET runner_id=EXCLUDED.runner_id,
            active_job_id=CASE
                WHEN omni_agent_runners.runner_id=EXCLUDED.runner_id
                THEN omni_agent_runners.active_job_id
                ELSE NULL
            END,
            lease_expires_at=EXCLUDED.lease_expires_at,
            updated_at=NOW()
        WHERE omni_agent_runners.runner_id=EXCLUDED.runner_id
           OR (
                omni_agent_runners.lease_expires_at <= NOW()
                AND NOT EXISTS (
                    SELECT 1 FROM omni_agent_jobs AS active_job
                    WHERE active_job.id=omni_agent_runners.active_job_id
                      AND active_job.status='working'
                      AND active_job.lease_expires_at > NOW()
                )
           )
        RETURNING *
        """,
        workspace_id,
        harness_id,
        runner_id,
        RUNNER_LEASE_SECONDS,
    )
    if row is None:
        raise AgentRunnerConflictError(
            f"another live runner owns harness {harness_id!r}; "
            f"reuse its local state or retry in at most {RUNNER_LEASE_SECONDS} seconds"
        )
    return row


async def _renew_runner_for_job(
    conn: Any,
    *,
    workspace_id: str,
    harness_id: str,
    job_id: UUID,
) -> None:
    owner = await conn.fetchrow(
        """
        UPDATE omni_agent_runners
        SET lease_expires_at=NOW() + ($4 * INTERVAL '1 second'),
            updated_at=NOW()
        WHERE workspace_id=$1 AND harness_id=$2 AND active_job_id=$3
        RETURNING runner_id
        """,
        workspace_id,
        harness_id,
        job_id,
        RUNNER_LEASE_SECONDS,
    )
    if owner is None:
        raise AgentLeaseError("the job's runner ownership is no longer live")


async def _clear_runner_job(
    *,
    workspace_id: str,
    harness_id: str,
    job_id: UUID,
) -> None:
    await execute(
        """
        UPDATE omni_agent_runners
        SET active_job_id=NULL,
            lease_expires_at=GREATEST(
                lease_expires_at,
                NOW() + ($4 * INTERVAL '1 second')
            ),
            updated_at=NOW()
        WHERE workspace_id=$1 AND harness_id=$2 AND active_job_id=$3
        """,
        workspace_id,
        harness_id,
        job_id,
        RUNNER_LEASE_SECONDS,
    )


async def _claim_next(
    workspace_id: str,
    harness_id: str,
    runner_id: UUID,
) -> tuple[dict[str, Any], str] | None:
    """Requeue expired leases, then atomically claim at most one runner job."""
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
        await conn.execute(
            """
            UPDATE omni_agent_runners AS runner
            SET active_job_id=NULL, updated_at=NOW()
            WHERE runner.workspace_id=$1 AND runner.harness_id=$2
              AND runner.runner_id=$3 AND runner.active_job_id IS NOT NULL
              AND NOT EXISTS (
                  SELECT 1 FROM omni_agent_jobs AS active_job
                  WHERE active_job.id=runner.active_job_id
                    AND active_job.status='working'
                    AND active_job.lease_expires_at > NOW()
              )
            """,
            workspace_id,
            harness_id,
            runner_id,
        )
        owner = await conn.fetchrow(
            """
            SELECT active_job_id
            FROM omni_agent_runners
            WHERE workspace_id=$1 AND harness_id=$2 AND runner_id=$3
              AND lease_expires_at > NOW()
            FOR UPDATE
            """,
            workspace_id,
            harness_id,
            runner_id,
        )
        if owner is None:
            raise AgentRunnerConflictError(
                f"runner ownership for harness {harness_id!r} expired or changed; reconnect"
            )
        if owner["active_job_id"] is not None:
            return None
        row = await conn.fetchrow(
            """
            WITH candidate AS (
                SELECT id
                FROM omni_agent_jobs
                WHERE workspace_id=$1 AND status='queued' AND expires_at > NOW()
                  AND (requested_harness_id IS NULL OR requested_harness_id=$2)
                ORDER BY created_at
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            UPDATE omni_agent_jobs AS job
            SET status='working', harness_id=$2, lease_hash=$3,
                lease_expires_at=NOW() + ($4 * INTERVAL '1 second'),
                claimed_at=NOW(), last_heartbeat_at=NOW(),
                attempts=attempts + 1, updated_at=NOW()
            FROM candidate
            WHERE job.id=candidate.id
            RETURNING job.*
            """,
            workspace_id,
            harness_id,
            token_hash,
            LEASE_SECONDS,
        )
        if row is not None:
            owner = await conn.fetchrow(
                """
                UPDATE omni_agent_runners
                SET active_job_id=$4,
                    lease_expires_at=NOW() + ($5 * INTERVAL '1 second'),
                    updated_at=NOW()
                WHERE workspace_id=$1 AND harness_id=$2 AND runner_id=$3
                  AND active_job_id IS NULL AND lease_expires_at > NOW()
                RETURNING runner_id
                """,
                workspace_id,
                harness_id,
                runner_id,
                row["id"],
                RUNNER_LEASE_SECONDS,
            )
            if owner is None:
                raise AgentRunnerConflictError(
                    f"runner ownership for harness {harness_id!r} changed during claim"
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
    runner_id: UUID,
    wait_seconds: int,
) -> tuple[dict[str, Any], str] | None:
    """Hold a reconnect-safe poll, waking on Redis and claiming from Postgres."""
    wait_seconds = max(0, min(wait_seconds, MAX_POLL_SECONDS))
    await _renew_runner_ownership(workspace_id, harness_id, runner_id)
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
        claimed = await _claim_next(workspace_id, harness_id, runner_id)
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
        return await _claim_next(workspace_id, harness_id, runner_id)
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
    async with acquire() as conn:
        record = await conn.fetchrow(
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
        if record is None:
            raise AgentLeaseError("lease expired, was cancelled, or belongs to another harness")
        await _renew_runner_for_job(
            conn,
            workspace_id=workspace_id,
            harness_id=harness_id,
            job_id=job_id,
        )
        row = dict(record)
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
    async with acquire() as conn:
        record = await conn.fetchrow(
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
        if record is None:
            raise AgentLeaseError("lease expired, was cancelled, or belongs to another harness")
        await _renew_runner_for_job(
            conn,
            workspace_id=workspace_id,
            harness_id=harness_id,
            job_id=job_id,
        )
        row = dict(record)
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
    if kind == "campaign.author":
        from app.services.campaign_candidate import (
            CampaignCandidateError,
            validate_candidate_graph,
        )

        try:
            return validate_candidate_graph(result)
        except CampaignCandidateError as exc:
            raise AgentHarnessError(str(exc)) from exc
    raise AgentHarnessError(f"unsupported agent job kind: {kind}")


async def review_result(
    kind: str,
    payload: dict[str, Any],
    result: dict[str, Any],
) -> dict[str, Any]:
    """Execute and compare a candidate using the job's frozen grounding."""
    if kind == "view.author":
        from app.services.view_grounding import review_view_candidate

        return await review_view_candidate(payload, result)
    if kind == "campaign.author":
        from app.services.campaign_grounding import review_campaign_candidate

        return await review_campaign_candidate(payload, result)
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
        SELECT id, kind, payload FROM omni_agent_jobs
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
    review = await review_result(str(owned["kind"]), owned.get("payload") or {}, validated)
    if not review.get("all_queries_valid", False):
        raise AgentHarnessError("the candidate contains a query that could not be executed")
    # Kind-agnostic refusal channel. A view candidate fails by being
    # unexecutable; a campaign candidate can execute perfectly and still be
    # unsafe — stranding live leads, or opening a send path nobody approves.
    # Such a proposal is refused at completion rather than stored for a human to
    # discover behind an Apply button.
    blocked = review.get("blocked_reason")
    if blocked:
        raise AgentHarnessError(str(blocked))
    row = await fetch_one(
        """
        UPDATE omni_agent_jobs
        SET status='succeeded', result=$4::jsonb, review=$5::jsonb, lease_hash=NULL,
            lease_expires_at=NULL, completed_at=NOW(), updated_at=NOW()
        WHERE id=$1 AND harness_id=$2 AND lease_hash=$3
          AND status='working' AND lease_expires_at > NOW()
        RETURNING *
        """,
        job_id,
        harness_id,
        _lease_hash(lease_token),
        json.dumps(validated),
        json.dumps(review),
    )
    if row is None:
        raise AgentLeaseError("lease expired while the result was being validated")
    await _clear_runner_job(
        workspace_id=workspace_id,
        harness_id=harness_id,
        job_id=job_id,
    )
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
    await _clear_runner_job(
        workspace_id=workspace_id,
        harness_id=harness_id,
        job_id=job_id,
    )
    await _set_presence(
        workspace_id,
        harness_id,
        "waiting",
        active_until=datetime.now(UTC) + timedelta(seconds=_PRESENCE_GRACE_SECONDS),
    )
    return row


async def list_recent_jobs(limit: int = 50) -> list[dict[str, Any]]:
    await _reconcile_stale_jobs()
    return await fetch_all(
        "SELECT * FROM omni_agent_jobs ORDER BY created_at DESC LIMIT $1",
        limit,
    )
