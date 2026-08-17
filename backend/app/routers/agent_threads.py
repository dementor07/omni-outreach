"""AGENT-THREAD-001 — the persistent conversation over a view or a campaign.

One surface serves both sides.  The browser opens a thread, queues questions and
instructions, and reads the transcript; a harness long-polls for outstanding
turns, answers the questions, and proposes against the instructions.

The distinction the whole design rests on is visible right here in the routes:
``/turns`` accepts a question or an instruction, ``/reply`` answers, and
``/propose`` is a *separate* call that only instruction turns can reach.  There
is no path by which asking something produces a diff.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field

from app.auth_apikey import get_workspace_any
from app.routers.agent_harness import AgentJobOut
from app.services import agent_harness, agent_threads
from app.services.agent_anchors import AnchorError, load_target
from app.services.agent_thread_proposals import ProposalError, propose_from_turns

router = APIRouter()

MAX_TURN_WAIT_SECONDS = 25
_TURN_POLL_INTERVAL_SECONDS = 1.0

TargetType = Literal["view", "workflow"]


class AnchorIn(BaseModel):
    ref: str = Field(min_length=1, max_length=100, description="A widget id or a node id")
    note: str = Field(min_length=1, max_length=1000)


class ThreadOpen(BaseModel):
    target_type: TargetType
    target_id: UUID
    reopen: bool = Field(
        default=False,
        description=(
            "Reopen a conversation a human deliberately ended. An agent-ended "
            "conversation reopens without this."
        ),
    )


class TurnIn(BaseModel):
    intent: Literal["question", "instruction"] = Field(
        description=(
            "'question' is answered in the thread and can never produce a change. "
            "'instruction' is what a proposal is built from."
        )
    )
    body: str = Field(default="", max_length=4000)
    anchors: list[AnchorIn] = Field(default_factory=list, max_length=12)


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=4000)
    intent: Literal["answer", "note"] = "answer"
    replies_to: list[UUID] = Field(default_factory=list)
    harness_id: str | None = Field(default=None, max_length=80)


class ProposeIn(BaseModel):
    turn_ids: list[UUID] = Field(min_length=1, max_length=25)
    harness_id: str = Field(min_length=1, max_length=80)


class TurnPollIn(BaseModel):
    harness_id: str = Field(min_length=1, max_length=80)
    wait_seconds: int = Field(default=MAX_TURN_WAIT_SECONDS, ge=0, le=MAX_TURN_WAIT_SECONDS)
    limit: int = Field(default=25, ge=1, le=100)


class TurnOut(BaseModel):
    id: UUID
    thread_id: UUID
    seq: int
    role: Literal["human", "agent"]
    intent: Literal["question", "instruction", "answer", "note"]
    body: str
    anchors: list[dict[str, Any]]
    status: Literal["queued", "answered", "proposed", "dropped"]
    job_id: UUID | None
    harness_id: str | None
    delivered_at: datetime | None
    created_at: datetime
    target_type: str | None = None
    target_id: UUID | None = None


class ThreadOut(BaseModel):
    id: UUID
    target_type: str
    target_id: UUID
    target_label: str | None = None
    status: Literal["open", "ended"]
    ended_by: Literal["human", "agent"] | None = None
    last_turn_at: datetime | None
    created_at: datetime
    turns: list[TurnOut] = Field(default_factory=list)
    open_proposal: AgentJobOut | None = None


def _fail(exc: Exception) -> HTTPException:
    if isinstance(exc, agent_threads.ThreadClosedError):
        return HTTPException(status_code=409, detail=str(exc))
    if isinstance(exc, agent_harness.AgentJobConflictError):
        return HTTPException(status_code=409, detail=str(exc))
    return HTTPException(status_code=422, detail=str(exc))


async def _thread_out(thread: dict[str, Any], *, after_seq: int | None = None) -> ThreadOut:
    turns = await agent_threads.list_turns(thread["id"], after_seq=after_seq)
    label: str | None = None
    try:
        label = (await load_target(str(thread["target_type"]), thread["target_id"])).label
    except AnchorError:
        # The target was deleted out from under an old conversation. That is a
        # readable transcript, not a 500.
        label = None
    open_job = await agent_harness.get_open_job_for_target(
        kind=agent_threads_job_kind(str(thread["target_type"])),
        target_type=str(thread["target_type"]),
        target_id=thread["target_id"],
    )
    return ThreadOut(
        **{key: thread[key] for key in ("id", "target_type", "target_id", "status", "ended_by")},
        target_label=label,
        last_turn_at=thread.get("last_turn_at"),
        created_at=thread["created_at"],
        turns=[TurnOut.model_validate(turn) for turn in turns],
        open_proposal=AgentJobOut.model_validate(open_job) if open_job else None,
    )


def agent_threads_job_kind(target_type: str) -> str:
    from app.services.agent_thread_proposals import JOB_KIND_BY_TARGET

    return JOB_KIND_BY_TARGET.get(target_type, "view.author")


# ── Static routes first: /open and /poll must not be swallowed by /{thread_id} ──


@router.post(
    "/open",
    response_model=ThreadOut,
    summary="Open or resume the conversation about a view or a campaign",
    description=(
        "Session identity is the target itself, not an opaque id: there is one "
        "live conversation per view or campaign. A conversation a human ended "
        "stays closed until reopen is set; one an agent ended resumes freely."
    ),
)
async def open_thread(body: ThreadOpen, ctx=Depends(get_workspace_any)) -> ThreadOut:
    try:
        thread = await agent_threads.open_thread(
            workspace_id=ctx.workspace_id,
            target_type=body.target_type,
            target_id=body.target_id,
            created_by=getattr(ctx, "user_id", None),
            reopen=body.reopen,
        )
    except AnchorError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except agent_threads.ThreadError as exc:
        raise _fail(exc) from exc
    return await _thread_out(thread)


@router.post(
    "/poll",
    response_model=list[TurnOut],
    summary="Long-poll for outstanding human turns across every conversation",
    description=(
        "Non-destructive by design: a returned turn is stamped as seen but stays "
        "queued until it is genuinely answered or proposed against. A harness "
        "that dies mid-thought re-reads the same turns instead of eating them."
    ),
)
async def poll_turns(body: TurnPollIn, ctx=Depends(get_workspace_any)) -> list[TurnOut]:
    deadline = asyncio.get_running_loop().time() + body.wait_seconds
    while True:
        turns = await agent_threads.pending_turns(
            workspace_id=ctx.workspace_id, limit=body.limit, harness_id=body.harness_id
        )
        if turns or asyncio.get_running_loop().time() >= deadline:
            return [TurnOut.model_validate(turn) for turn in turns]
        await asyncio.sleep(_TURN_POLL_INTERVAL_SECONDS)


# ── Dynamic routes ─────────────────────────────────────────────────────────────


@router.get(
    "/{thread_id}",
    response_model=ThreadOut,
    summary="Read a conversation, optionally only what is new",
)
async def get_thread(
    thread_id: UUID,
    after_seq: int | None = Query(default=None, ge=0),
    _ctx=Depends(get_workspace_any),
) -> ThreadOut:
    thread = await agent_threads.get_thread(thread_id)
    if thread is None:
        raise HTTPException(status_code=404, detail="conversation not found")
    return await _thread_out(thread, after_seq=after_seq)


@router.post(
    "/{thread_id}/turns",
    response_model=TurnOut,
    status_code=status.HTTP_201_CREATED,
    summary="Queue a question or an instruction, optionally pinned to specific parts",
)
async def post_turn(thread_id: UUID, body: TurnIn, ctx=Depends(get_workspace_any)) -> TurnOut:
    try:
        turn, _snapshot = await agent_threads.post_turn(
            workspace_id=ctx.workspace_id,
            thread_id=thread_id,
            intent=body.intent,
            body=body.body,
            anchors=[anchor.model_dump() for anchor in body.anchors],
            created_by=getattr(ctx, "user_id", None),
        )
    except agent_threads.ThreadError as exc:
        raise _fail(exc) from exc
    return TurnOut.model_validate(turn)


@router.post(
    "/{thread_id}/reply",
    response_model=TurnOut,
    status_code=status.HTTP_201_CREATED,
    summary="Post the agent's answer and retire the turns it addresses",
)
async def reply(thread_id: UUID, body: ReplyIn, ctx=Depends(get_workspace_any)) -> TurnOut:
    try:
        turn = await agent_threads.reply(
            workspace_id=ctx.workspace_id,
            thread_id=thread_id,
            body=body.body,
            intent=body.intent,
            replies_to=body.replies_to or None,
            harness_id=body.harness_id,
        )
    except agent_threads.ThreadError as exc:
        raise _fail(exc) from exc
    return TurnOut.model_validate(turn)


@router.post(
    "/{thread_id}/propose",
    response_model=AgentJobOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Build one grounded proposal from queued instruction turns",
    description=(
        "Only instruction turns reach here. The proposal is queued through the "
        "existing job broker, so it inherits leases, review, and the requirement "
        "that a human applies it. A campaign proposal is additionally refused at "
        "completion if it would strand live leads or open an unapproved send path."
    ),
)
async def propose(thread_id: UUID, body: ProposeIn, ctx=Depends(get_workspace_any)) -> AgentJobOut:
    try:
        job = await propose_from_turns(
            workspace_id=ctx.workspace_id,
            thread_id=thread_id,
            turn_ids=body.turn_ids,
            harness_id=body.harness_id,
            created_by=getattr(ctx, "user_id", None),
        )
    except (ProposalError, agent_threads.ThreadError, agent_harness.AgentHarnessError) as exc:
        raise _fail(exc) from exc
    return AgentJobOut.model_validate(job)


@router.post(
    "/{thread_id}/end",
    response_model=ThreadOut,
    summary="End a conversation",
)
async def end_thread(
    thread_id: UUID,
    ended_by: Literal["human", "agent"] = Query(default="human"),
    _ctx=Depends(get_workspace_any),
) -> ThreadOut:
    try:
        thread = await agent_threads.end_thread(thread_id=thread_id, ended_by=ended_by)
    except agent_threads.ThreadError as exc:
        raise _fail(exc) from exc
    return await _thread_out(thread)
