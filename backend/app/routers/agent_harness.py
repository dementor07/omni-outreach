"""Provider-neutral long-poll API for Codex / Claude Code / OpenCode harnesses."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from app.auth import AuthContext, get_current_workspace
from app.auth_apikey import get_apikey_workspace, get_workspace_any
from app.services import agent_harness

router = APIRouter()

JobStatus = Literal["queued", "working", "succeeded", "failed", "cancelled", "expired"]


class AgentJobOut(BaseModel):
    id: UUID
    kind: str
    target_type: str
    target_id: UUID
    status: JobStatus
    result: dict[str, Any] | None
    progress: list[dict[str, Any]]
    error: str | None
    requested_harness_id: str | None
    harness_id: str | None
    attempts: int
    claimed_at: datetime | None
    last_heartbeat_at: datetime | None
    completed_at: datetime | None
    applied_at: datetime | None
    expires_at: datetime
    created_at: datetime
    updated_at: datetime


class AgentWorkerOut(BaseModel):
    harness_id: str
    state: Literal["listening", "working", "waiting"]
    job_id: UUID | None = None
    last_seen_at: datetime
    active_until: datetime


class AgentPollRequest(BaseModel):
    harness_id: str = Field(
        min_length=1,
        max_length=80,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    wait_seconds: int = Field(agent_harness.MAX_POLL_SECONDS, ge=0, le=agent_harness.MAX_POLL_SECONDS)


class AgentJobClaim(BaseModel):
    id: UUID
    kind: str
    target_type: str
    target_id: UUID
    payload: dict[str, Any]
    lease_token: str = Field(description="Opaque lease; never log or store server-side in plaintext")
    lease_expires_at: datetime
    attempts: int


class LeaseRequest(BaseModel):
    harness_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")
    lease_token: str = Field(min_length=20, max_length=200)


class ProgressRequest(LeaseRequest):
    message: str = Field(min_length=1, max_length=500)


class CompleteRequest(LeaseRequest):
    result: dict[str, Any]


class FailRequest(LeaseRequest):
    error: str = Field(min_length=1, max_length=2000)


def _out(row: dict[str, Any]) -> AgentJobOut:
    return AgentJobOut.model_validate(row)


def _broker_error(exc: agent_harness.AgentHarnessError) -> HTTPException:
    code = status.HTTP_409_CONFLICT if isinstance(exc, agent_harness.AgentLeaseError) else status.HTTP_422_UNPROCESSABLE_ENTITY
    return HTTPException(status_code=code, detail=str(exc))


@router.get(
    "/workers",
    response_model=list[AgentWorkerOut],
    summary="Active harness presence for this workspace",
    description="Ephemeral Redis-backed presence. An empty list is definitive: no harness currently holds a poll or live lease.",
)
async def workers(ctx: AuthContext = Depends(get_workspace_any)) -> list[AgentWorkerOut]:
    rows = await agent_harness.list_active_workers(ctx.workspace_id)
    return [AgentWorkerOut.model_validate(row) for row in rows]


@router.get("/jobs", response_model=list[AgentJobOut], summary="Recent agent jobs")
async def jobs(
    _: AuthContext = Depends(get_current_workspace),
    limit: int = 50,
) -> list[AgentJobOut]:
    bounded = max(1, min(limit, 100))
    return [_out(row) for row in await agent_harness.list_recent_jobs(bounded)]


@router.post(
    "/jobs/poll",
    response_model=AgentJobClaim,
    responses={204: {"description": "No queued work before the held poll elapsed"}},
    summary="Hold a poll and atomically claim the oldest queued job",
    description=(
        "API-key only. Presence changes to listening for the held poll and working "
        "after an atomic SKIP LOCKED claim. Reconnect after a 204; queued work is durable."
    ),
)
async def poll(
    body: AgentPollRequest,
    ctx: AuthContext = Depends(get_apikey_workspace),
) -> AgentJobClaim | Response:
    claimed = await agent_harness.poll_for_job(
        ctx.workspace_id,
        body.harness_id,
        body.wait_seconds,
    )
    if claimed is None:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    row, lease_token = claimed
    return AgentJobClaim(
        id=row["id"],
        kind=row["kind"],
        target_type=row["target_type"],
        target_id=row["target_id"],
        payload=row["payload"],
        lease_token=lease_token,
        lease_expires_at=row["lease_expires_at"],
        attempts=row["attempts"],
    )


@router.get("/jobs/{job_id}", response_model=AgentJobOut, summary="Read one agent job")
async def job(
    job_id: UUID,
    _: AuthContext = Depends(get_workspace_any),
) -> AgentJobOut:
    row = await agent_harness.get_job(job_id)
    if row is None:
        raise HTTPException(status_code=404, detail="agent job not found")
    return _out(row)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=AgentJobOut,
    summary="Cancel one queued or working agent job",
)
async def cancel(
    job_id: UUID,
    _: AuthContext = Depends(get_current_workspace),
) -> AgentJobOut:
    row = await agent_harness.cancel_job(job_id)
    if row is None:
        current = await agent_harness.get_job(job_id)
        if current is None:
            raise HTTPException(status_code=404, detail="agent job not found")
        raise HTTPException(status_code=409, detail=f"job is already {current['status']}")
    return _out(row)


@router.post("/jobs/{job_id}/heartbeat", response_model=AgentJobOut, summary="Renew a live job lease")
async def heartbeat(
    job_id: UUID,
    body: LeaseRequest,
    ctx: AuthContext = Depends(get_apikey_workspace),
) -> AgentJobOut:
    try:
        return _out(await agent_harness.heartbeat_job(
            workspace_id=ctx.workspace_id,
            job_id=job_id,
            harness_id=body.harness_id,
            lease_token=body.lease_token,
        ))
    except agent_harness.AgentHarnessError as exc:
        raise _broker_error(exc) from exc


@router.post("/jobs/{job_id}/progress", response_model=AgentJobOut, summary="Append one bounded progress event")
async def progress(
    job_id: UUID,
    body: ProgressRequest,
    ctx: AuthContext = Depends(get_apikey_workspace),
) -> AgentJobOut:
    try:
        return _out(await agent_harness.append_progress(
            workspace_id=ctx.workspace_id,
            job_id=job_id,
            harness_id=body.harness_id,
            lease_token=body.lease_token,
            message=body.message,
        ))
    except agent_harness.AgentHarnessError as exc:
        raise _broker_error(exc) from exc


@router.post("/jobs/{job_id}/complete", response_model=AgentJobOut, summary="Validate and store the candidate result")
async def complete(
    job_id: UUID,
    body: CompleteRequest,
    ctx: AuthContext = Depends(get_apikey_workspace),
) -> AgentJobOut:
    try:
        return _out(await agent_harness.complete_job(
            workspace_id=ctx.workspace_id,
            job_id=job_id,
            harness_id=body.harness_id,
            lease_token=body.lease_token,
            result=body.result,
        ))
    except agent_harness.AgentHarnessError as exc:
        raise _broker_error(exc) from exc


@router.post("/jobs/{job_id}/fail", response_model=AgentJobOut, summary="Finish a job with a structured failure")
async def fail(
    job_id: UUID,
    body: FailRequest,
    ctx: AuthContext = Depends(get_apikey_workspace),
) -> AgentJobOut:
    try:
        return _out(await agent_harness.fail_job(
            workspace_id=ctx.workspace_id,
            job_id=job_id,
            harness_id=body.harness_id,
            lease_token=body.lease_token,
            error=body.error,
        ))
    except agent_harness.AgentHarnessError as exc:
        raise _broker_error(exc) from exc
